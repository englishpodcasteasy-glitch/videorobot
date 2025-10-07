# -*- coding: utf-8 -*-
"""
VideoRobot — HTTP Backend (نسخه تمیز و کامل)

Flask REST API برای:
- مدیریت فایل‌ها و پوشه‌ها
- رونویسی صوت
- رندر ویدئو (async با job queue)
- دانلود نتایج
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS


# ===========================================================================
# SECTION 1: راه‌اندازی Logging
# ===========================================================================

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
logging.basicConfig(
    level=os.getenv("VR_LOG_LEVEL", "INFO"),
    format=LOG_FORMAT
)
log = logging.getLogger("VideoRobot.http")


# ===========================================================================
# SECTION 2: Import ماژول‌های داخلی
# ===========================================================================

try:
    # Import نسبی (وقتی به عنوان package اجرا می‌شود)
    from . import __version__ as VR_VERSION
    from .config import (
        Paths, ProjectCfg, AudioCfg, CaptionCfg, FigureCfg,
        IntroOutroCfg, CTACfg, BGMCfg, BrollCfg, VisualCfg, ShortsCfg,
        Aspect, CaptionPosition, ShortsMode, FONTS,
    )
    from .renderer import Renderer
    from .scheduler import Scheduler
    from .utils import docs_guard, mount_drive_once, resolve_drive_base
except ImportError:
    # Import مستقیم (اجرای standalone)
    VR_VERSION = "1.0.0"
    sys.path.insert(0, str(Path(__file__).parent.resolve()))
    
    from config import (
        Paths, ProjectCfg, AudioCfg, CaptionCfg, FigureCfg,
        IntroOutroCfg, CTACfg, BGMCfg, BrollCfg, VisualCfg, ShortsCfg,
        Aspect, CaptionPosition, ShortsMode, FONTS,
    )
    from renderer import Renderer
    from scheduler import Scheduler
    from utils import docs_guard, mount_drive_once, resolve_drive_base


# ===========================================================================
# SECTION 3: مدیریت مسیرها
# ===========================================================================

def _ensure_directories(paths: Paths) -> None:
    """ایجاد تمام دایرکتوری‌های مورد نیاز"""
    required_dirs = [
        paths.tmp,
        paths.out_local,
        paths.assets,
        paths.figures,
        paths.music,
        paths.broll,
        FONTS,
    ]
    
    for directory in required_dirs:
        directory.mkdir(parents=True, exist_ok=True)


def _initialize_paths(use_drive: bool = False) -> Paths:
    """
    راه‌اندازی و ساخت ساختار مسیرها
    
    Args:
        use_drive: آیا از Google Drive استفاده شود
    
    Returns:
        شیء Paths پیکربندی شده
    """
    docs_guard()
    
    base_local = Path(
        os.getenv("VR_BASE_LOCAL", "/content/VideoRobot")
    ).resolve()
    
    base_drive: Optional[Path] = None
    
    if use_drive:
        try:
            if mount_drive_once():
                base_drive = resolve_drive_base()
        except Exception as e:
            log.warning("خطا در mount کردن Drive: %s", e)
    
    paths = Paths(
        base_local=base_local,
        base_drive=base_drive,
        tmp=base_local / "_vr_tmp",
        out_local=base_local / "_vr_out",
        out_drive=(base_drive / "Output") if base_drive else None,
        assets=base_local / "Assets",
        figures=base_local / "Assets" / "Figures",
        music=base_local / "Assets" / "Music",
        broll=base_local / "Broll",
    )
    
    _ensure_directories(paths)
    return paths


# مسیرهای global
PATHS = _initialize_paths(use_drive=True)


# ===========================================================================
# SECTION 4: توابع کمکی FFmpeg
# ===========================================================================

def _run_ffmpeg(cmd: List[str], description: str = "FFmpeg operation") -> None:
    """
    اجرای دستور FFmpeg با مدیریت خطا
    
    Args:
        cmd: دستور FFmpeg
        description: توضیح عملیات
    
    Raises:
        RuntimeError: در صورت شکست
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        log.info("%s انجام شد", description)
    except subprocess.CalledProcessError as e:
        log.error("%s شکست خورد: %s", description, e.stderr)
        raise RuntimeError(f"{description} failed: {e.stderr}")


def _concatenate_audio_files(basenames: List[str]) -> str:
    """
    ترکیب چند فایل صوتی به یک فایل
    
    Args:
        basenames: لیست نام فایل‌ها در Assets
    
    Returns:
        نام فایل خروجی ترکیب شده
    """
    if not basenames or len(basenames) == 1:
        return basenames[0] if basenames else "voice.m4a"
    
    # نام پایدار بر اساس hash
    key = "|".join(basenames).encode("utf-8", "ignore")
    hash_str = hashlib.sha1(key).hexdigest()[:10]
    output_name = f"concat_{hash_str}.wav"
    output_path = PATHS.assets / output_name
    
    # استفاده از cache اگر موجود است
    if output_path.exists():
        log.info("استفاده از فایل ترکیب شده موجود: %s", output_name)
        return output_name
    
    # ساخت فایل لیست
    list_file = PATHS.tmp / f"concat_{hash_str}.txt"
    lines = []
    for basename in basenames:
        file_path = (PATHS.assets / basename).as_posix().replace("'", r"\'")
        lines.append(f"file '{file_path}'")
    
    list_file.write_text("\n".join(lines), encoding="utf-8")
    
    # اجرای concat
    cmd = [
        "ffmpeg", "-y", "-hide_banner",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    
    _run_ffmpeg(cmd, "ترکیب فایل‌های صوتی")
    return output_name


def _copy_file_to_assets(source_path: str | Path) -> str:
    """
    کپی فایل به پوشه Assets
    
    Args:
        source_path: مسیر فایل مبدا
    
    Returns:
        نام فایل (basename)
    
    Raises:
        FileNotFoundError: اگر فایل وجود نداشته باشد
        RuntimeError: در صورت خطای کپی
    """
    source = Path(str(source_path))
    
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"فایل پیدا نشد: {source}")
    
    destination = PATHS.assets / source.name
    
    # کپی فقط اگر مسیر متفاوت باشد
    if source.resolve() != destination.resolve():
        try:
            shutil.copy2(str(source), str(destination))
        except Exception as e:
            raise RuntimeError(
                f"خطا در کپی به Assets: {source} -> {destination} ({e})"
            )
    
    return source.name


# ===========================================================================
# SECTION 5: پارسرهای Enum
# ===========================================================================

def _parse_aspect(value: str) -> Aspect:
    """تبدیل رشته به Aspect"""
    aspect_map = {
        "9:16": Aspect.V9x16,
        "1:1": Aspect.V1x1,
        "16:9": Aspect.V16x9,
    }
    return aspect_map.get(str(value).strip(), Aspect.V9x16)


def _parse_caption_position(value: str) -> CaptionPosition:
    """تبدیل رشته به CaptionPosition"""
    position_map = {
        "Top": CaptionPosition.TOP,
        "Middle": CaptionPosition.MIDDLE,
        "Bottom": CaptionPosition.BOTTOM,
    }
    return position_map.get(str(value).strip(), CaptionPosition.BOTTOM)


def _parse_shorts_mode(value: str) -> ShortsMode:
    """تبدیل رشته به ShortsMode"""
    mode_map = {
        "Off": ShortsMode.OFF,
        "Auto": ShortsMode.AUTO,
        "Force": ShortsMode.FORCE,
    }
    return mode_map.get(str(value).strip(), ShortsMode.OFF)


# ===========================================================================
# SECTION 6: ساخت Config از JSON
# ===========================================================================

def _build_config_from_json(data: Dict[str, Any]) -> Tuple[ProjectCfg, List[str]]:
    """
    تبدیل JSON ورودی به ProjectCfg
    
    Args:
        data: دیکشنری JSON از frontend
    
    Returns:
        (config, used_sources): تنظیمات و لیست فایل‌های استفاده شده
    
    Raises:
        ValueError: در صورت نامعتبر بودن config
    """
    used_sources: List[str] = []
    
    # === Audio ===
    audio_segments = data.get("audioSegments") or []
    audio_paths = [
        str(seg.get("path", "")).strip()
        for seg in audio_segments
        if isinstance(seg, dict) and seg.get("path")
    ]
    
    audio_filename = "voice.m4a"
    
    if audio_paths:
        # کپی همه فایل‌ها به Assets
        asset_basenames = []
        for path in audio_paths:
            basename = _copy_file_to_assets(path)
            asset_basenames.append(basename)
            used_sources.append(path)
        
        # ترکیب اگر چند فایل است
        audio_filename = _concatenate_audio_files(asset_basenames)
    
    # === Background ===
    bg_path = str(data.get("bgPath") or "").strip() or "bg.jpg"
    
    if bg_path:
        bg_filename = _copy_file_to_assets(bg_path)
        used_sources.append(bg_path)
    else:
        bg_filename = "bg.jpg"
    
    # === Captions/Subtitles ===
    config_root = data.get("config") or {}
    
    # جستجو در چند جای ممکن
    subtitles_data = (
        config_root.get('subtitles') or
        config_root.get('captions') or
        data.get('subtitles') or
        data.get('captions') or
        {}
    )
    
    captions = CaptionCfg(
        font_choice=None,
        font_name=None,
        font_size=int(subtitles_data.get("fontSize", 92)),
        active_color=str(subtitles_data.get("primaryColor", "#FFFFFF")),
        keyword_color=str(subtitles_data.get("highlightColor", "#FFD700")),
        border_thickness=int(
            subtitles_data.get("outlineWidth",
            subtitles_data.get("border", 4))
        ),
        max_words_per_line=int(subtitles_data.get("maxWordsPerLine", 6)),
        max_words_per_caption=int(subtitles_data.get("maxWordsPerCaption", 12)),
        position=_parse_caption_position(subtitles_data.get("position", "Bottom")),
        margin_v=int(subtitles_data.get("marginV", 70)),
    )
    
    # === Visual ===
    visual_data = config_root.get('visual') or data.get('visual') or {}
    aspect_ratio = (
        visual_data.get('aspect') or
        config_root.get('aspectRatio') or
        data.get('aspectRatio') or
        '9:16'
    )
    ken_burns = bool(
        visual_data.get('ken_burns', False) or
        config_root.get('kenBurns', False)
    )
    
    visual = VisualCfg(
        bg_image=bg_filename,
        aspect=_parse_aspect(aspect_ratio),
        ken_burns=ken_burns
    )
    
    # === Audio Advanced ===
    audio_advanced = config_root.get('audio') or data.get('audio') or {}
    
    audio = AudioCfg(
        filename=audio_filename,
        whisper_model=str(audio_advanced.get("whisperModel", "medium")),
        use_vad=bool(audio_advanced.get("useVad", True)),
        target_lufs=float(audio_advanced.get("targetLufs", -16.0)),
        target_lra=float(audio_advanced.get("targetLra", 11.0)),
        target_tp=float(audio_advanced.get("targetTp", -2.0)),
    )
    
    # === بقیه تنظیمات (با مقادیر پیش‌فرض) ===
    figures = FigureCfg(use=False, duration_s=1.8)
    
    intro_outro = IntroOutroCfg(
        intro_mp4=None,
        intro_key=False,
        outro_mp4=None,
        outro_key=False
    )
    
    cta = CTACfg(
        loop_mp4=None,
        start_s=30.0,
        repeat_s=120.0,
        key_color="#00FF00",
        similarity=0.23,
        blend=0.05,
        position=CaptionPosition.MIDDLE
    )
    
    bgm = BGMCfg(
        name=None,
        gain_db=-20.0,
        auto_duck=True,
        duck_threshold=-30.0,
        duck_ratio=12.0,
        duck_attack=20,
        duck_release=300
    )
    
    broll = BrollCfg(
        use=False,
        first_at=5.0,
        every_s=14.0,
        duration_s=4.0
    )
    
    shorts_data = config_root.get('shorts') or data.get('shorts') or {}
    shorts_mode = (
        shorts_data.get('mode') or
        config_root.get('shortsMode') or
        'Off'
    )
    
    shorts = ShortsCfg(
        mode=_parse_shorts_mode(shorts_mode),
        min_s=int(shorts_data.get('min_s', 45)),
        max_s=int(shorts_data.get('max_s', 90)),
    )
    
    # === ساخت ProjectCfg ===
    config = ProjectCfg(
        audio=audio,
        captions=captions,
        figures=figures,
        intro_outro=intro_outro,
        cta=cta,
        bgm=bgm,
        broll=broll,
        visual=visual,
        shorts=shorts,
        dry_run=False,
        timestamp_offset=0.0,
    )
    
    # اعتبارسنجی
    try:
        config = config.validate()
    except Exception as e:
        raise ValueError(f"تنظیمات نامعتبر: {e}") from e
    
    return config, used_sources


# ===========================================================================
# SECTION 7: مدیریت Job Queue
# ===========================================================================

JOBS_LOCK = threading.Lock()
JOBS: Dict[str, Dict[str, Any]] = {}


def _cleanup_old_jobs(max_jobs: int) -> None:
    """حذف job های قدیمی برای محدود کردن حافظه"""
    with JOBS_LOCK:
        if len(JOBS) <= max_jobs:
            return
        
        # حذف قدیمی‌ترین‌ها
        old_count = len(JOBS) - max_jobs
        for key in list(JOBS.keys())[:old_count]:
            JOBS.pop(key, None)


def _update_job(job_id: str, **fields: Any) -> None:
    """به‌روزرسانی وضعیت job"""
    with JOBS_LOCK:
        job = JOBS.setdefault(
            job_id,
            {
                "status": "queued",
                "progress": {"percentage": 0, "message": ""}
            }
        )
        job.update(fields)


def _get_job_status(job_id: str) -> Dict[str, Any]:
    """دریافت وضعیت job"""
    with JOBS_LOCK:
        return dict(JOBS.get(job_id, {}))


def _render_worker(job_id: str, preset_json: Dict[str, Any], max_jobs: int) -> None:
    """
    Worker thread برای رندر ویدئو
    
    این تابع در thread جداگانه اجرا می‌شود.
    """
    try:
        # مرحله 1: آماده‌سازی
        _update_job(
            job_id,
            status="running",
            progress={"percentage": 5, "message": "آماده‌سازی ورودی‌ها..."}
        )
        
        config, _used_sources = _build_config_from_json(preset_json)
        renderer = Renderer(PATHS)
        
        # مرحله 2: رونویسی و رندر
        _update_job(
            job_id,
            progress={"percentage": 35, "message": "رونویسی و ساخت زیرنویس..."}
        )
        
        output_video, _norm_audio, _filter_count, _srt_path = renderer.render(config)
        
        # مرحله 3: اتمام
        video_name = Path(output_video).name
        video_url = f"/download?file={video_name}"
        
        _update_job(
            job_id,
            status="done",
            progress={"percentage": 100, "message": "تمام شد."},
            videoUrl=video_url
        )
        
    except Exception as e:
        log.exception("رندر job شکست خورد: %s", e)
        _update_job(
            job_id,
            status="error",
            error=str(e),
            progress={"percentage": 0, "message": "خطا رخ داد."}
        )
    
    finally:
        _cleanup_old_jobs(max_jobs)


# ===========================================================================
# SECTION 8: Flask Application
# ===========================================================================

app = Flask(__name__)
CORS(app)


@app.get("/health")
def health_check() -> Any:
    """بررسی سلامت سرویس"""
    return jsonify({
        "ok": True,
        "version": VR_VERSION,
        "assets": str(PATHS.assets),
        "output": str(PATHS.out_local)
    }), 200


def _is_path_under_root(path: Path, root: Path) -> bool:
    """بررسی اینکه آیا path زیرمجموعه root است"""
    try:
        # Python 3.9+
        return path.resolve().is_relative_to(root.resolve())
    except AttributeError:
        # Python 3.8
        resolved_path = str(path.resolve())
        resolved_root = str(root.resolve())
        return (
            resolved_path == resolved_root or
            resolved_path.startswith(resolved_root + os.sep)
        )


@app.get("/list-files")
def list_files() -> Any:
    """
    لیست فایل‌های یک پوشه
    
    Query params:
        path: مسیر مطلق پوشه
    
    Returns:
        لیست فایل‌ها و پوشه‌ها با اطلاعات
    """
    path_str = (request.args.get("path") or "").strip()
    
    if not path_str:
        return jsonify({"error": "پارامتر 'path' الزامی است"}), 400
    
    directory = Path(path_str).expanduser()
    
    if not directory.exists():
        return jsonify({"error": "PATH_NOT_FOUND"}), 404
    
    if not directory.is_dir():
        return jsonify({"error": "NOT_A_DIRECTORY"}), 400
    
    # بررسی دسترسی (فقط زیر مسیرهای مجاز)
    allowed_roots = [PATHS.assets, PATHS.out_local]
    if PATHS.base_drive:
        allowed_roots.append(PATHS.base_drive)
    
    if not any(_is_path_under_root(directory, root) for root in allowed_roots):
        return jsonify({"error": "FORBIDDEN"}), 403
    
    # خواندن محتویات
    items = []
    try:
        for child in sorted(directory.iterdir(), key=lambda x: x.name.lower()):
            stats = child.stat()
            items.append({
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "size": 0 if child.is_dir() else stats.st_size,
                "mtime": int(stats.st_mtime),
            })
    except PermissionError:
        return jsonify({"error": "PERMISSION_DENIED"}), 403
    
    return jsonify(items), 200


@app.post("/transcribe")
def transcribe() -> Any:
    """
    رونویسی فایل صوتی
    
    Body:
        {
          "audioPaths": ["path/to/audio.mp3"],
          "model": "medium",  // optional
          "useVad": true      // optional
        }
    
    Returns:
        {"transcript": "..."}
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        audio_paths = data.get("audioPaths") or []
        
        if not isinstance(audio_paths, list) or not audio_paths:
            return jsonify({"error": "audioPaths باید آرایه غیرخالی باشد"}), 400
        
        first_audio = str(audio_paths[0]).strip()
        if not first_audio:
            return jsonify({"error": "مسیر اولین صوت خالی است"}), 400
        
        # کپی به Assets
        basename = _copy_file_to_assets(first_audio)
        
        # رونویسی
        scheduler = Scheduler()
        words = scheduler.transcribe_words(
            PATHS.assets / basename,
            size=str(data.get("model", "medium")),
            use_vad=bool(data.get("useVad", True)),
        )
        
        # ترکیب کلمات
        transcript = " ".join(word.get("raw", "") for word in words).strip()
        
        return jsonify({"transcript": transcript}), 200
        
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        log.exception("رونویسی شکست خورد: %s", e)
        return jsonify({"error": str(e)}), 500


@app.post("/render")
def render_video() -> Any:
    """
    شروع رندر ویدئو (async)
    
    Body:
        ProjectPreset JSON
    
    Returns:
        {"jobId": "..."}
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        
        # ایجاد job جدید
        job_id = uuid.uuid4().hex
        _update_job(
            job_id,
            status="queued",
            progress={"percentage": 1, "message": "در صف قرار گرفت."}
        )
        
        # شروع worker thread
        max_jobs = int(os.getenv("VR_MAX_JOBS", "100"))
        threading.Thread(
            target=_render_worker,
            args=(job_id, data, max_jobs),
            daemon=True
        ).start()
        
        return jsonify({"jobId": job_id}), 200
        
    except Exception as e:
        log.exception("خطا در ایجاد job رندر: %s", e)
        return jsonify({"error": str(e)}), 500


@app.get("/status")
def job_status() -> Any:
    """
    بررسی وضعیت job
    
    Query params:
        jobId یا id: شناسه job
    
    Returns:
        {
          "status": "queued|running|done|error",
          "progress": {"percentage": 0-100, "message": "..."},
          "videoUrl": "...",  // اگر done
          "error": "..."      // اگر error
        }
    """
    job_id = (
        request.args.get("jobId") or
        request.args.get("id") or
        ""
    ).strip()
    
    if not job_id:
        return jsonify({"error": "jobId الزامی است"}), 400
    
    job = _get_job_status(job_id)
    
    if not job:
        return jsonify({"error": "jobId پیدا نشد"}), 404
    
    return jsonify(job), 200


@app.get("/download")
def download_file() -> Any:
    """
    دانلود فایل خروجی
    
    Query params:
        file: نام فایل (فقط basename)
    
    Returns:
        فایل برای دانلود
    """
    filename = request.args.get("file", "").strip()
    
    if not filename:
        return jsonify({"error": "پارامتر 'file' الزامی است"}), 400
    
    # امنیت: جلوگیری از path traversal
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return jsonify({"error": "نام فایل نامعتبر"}), 400
    
    file_path = PATHS.out_local / filename
    
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": "فایل پیدا نشد"}), 404
    
    return send_from_directory(
        PATHS.out_local,
        filename,
        as_attachment=False
    )


# ===========================================================================
# SECTION 9: Main Entry Point
# ===========================================================================

if __name__ == "__main__":
    host = os.getenv("VR_HOST", "0.0.0.0")
    port = int(os.getenv("VR_PORT", "8000"))
    
    log.info(
        "🚀 VideoRobot HTTP Backend %s در حال اجرا بر روی %s:%d",
        VR_VERSION, host, port
    )
    
    app.run(host=host, port=port, debug=False)


# ===========================================================================
# پایان فایل
# ===========================================================================