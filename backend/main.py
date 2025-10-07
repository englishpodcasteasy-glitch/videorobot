# -*- coding: utf-8 -*-
"""
VideoRobot — HTTP Backend (نسخه بهبود یافته برای Colab + Drive + Tunnel)

Flask REST API:
- مدیریت فایل‌ها و پوشه‌ها
- رونویسی صوت
- رندر ویدئو (async با job queue)
- دانلود نتایج
- ذخیره خروجی در Google Drive
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS

# بخش داخلی
from config import Paths, ProjectCfg, AudioCfg, CaptionCfg, FigureCfg, IntroOutroCfg, CTACfg, BGMCfg, BrollCfg, VisualCfg, ShortsCfg, Aspect, CaptionPosition, ShortsMode, FONTS
from renderer import Renderer
from scheduler import Scheduler
from utils import docs_guard, mount_drive_once, resolve_drive_base

# تنظیمات لوگ
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
logging.basicConfig(level=os.getenv("VR_LOG_LEVEL", "INFO"), format=LOG_FORMAT)
log = logging.getLogger("VideoRobot.http")

# ============ مدیریت مسیرها و اولیه‌سازی ============

def _ensure_directories(paths: Paths) -> None:
    required = [
        paths.tmp,
        paths.out_local,
        paths.assets,
        paths.figures,
        paths.music,
        paths.broll,
        FONTS,
    ]
    for d in required:
        d.mkdir(parents=True, exist_ok=True)

def _initialize_paths(use_drive: bool = True) -> Paths:
    docs_guard()
    base_local = Path(os.getenv("VR_BASE_LOCAL", "/content/VideoRobot")).resolve()
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
        out_drive=(base_drive / "Output") if base_drive is not None else None,
        assets=base_local / "Assets",
        figures=base_local / "Assets" / "Figures",
        music=base_local / "Assets" / "Music",
        broll=base_local / "Broll",
    )
    _ensure_directories(paths)
    return paths

PATHS = _initialize_paths(use_drive=True)

# ============ توابع کمکی FFmpeg و فایل ============

def _run_ffmpeg(cmd: List[str], description: str = "FFmpeg operation") -> None:
    try:
        result = __import__("subprocess").run(cmd, capture_output=True, text=True, check=True)
        log.info("%s انجام شد", description)
    except __import__("subprocess").CalledProcessError as e:
        log.error("%s شکست خورد: %s", description, e.stderr)
        raise RuntimeError(f"{description} failed: {e.stderr}")

def _concatenate_audio_files(basenames: List[str]) -> str:
    if not basenames:
        return ""
    if len(basenames) == 1:
        return basenames[0]

    key = "|".join(basenames).encode("utf-8", "ignore")
    hash_str = hashlib.sha1(key).hexdigest()[:10]
    output_name = f"concat_{hash_str}.wav"
    output_path = PATHS.assets / output_name

    if output_path.exists():
        log.info("استفاده از فایل ترکیب شده موجود: %s", output_name)
        return output_name

    list_file = PATHS.tmp / f"concat_{hash_str}.txt"
    lines = []
    for b in basenames:
        fp = (PATHS.assets / b).as_posix().replace("'", r"\'")
        lines.append(f"file '{fp}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        "ffmpeg", "-y", "-hide_banner",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    _run_ffmpeg(cmd, "ترکیب فایل‌های صوتی")
    return output_name

def _copy_file_to_assets(src: str | Path) -> str:
    source = Path(str(src))
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"فایل پیدا نشد: {source}")
    dest = PATHS.assets / source.name
    if source.resolve() != dest.resolve():
        try:
            shutil.copy2(str(source), str(dest))
        except Exception as e:
            raise RuntimeError(f"خطا در کپی به Assets: {source} -> {dest}: {e}")
    return source.name

# ============ پارسرها ============

def _parse_aspect(value: str) -> Aspect:
    m = {
        "9:16": Aspect.V9x16,
        "16:9": Aspect.V16x9,
        "1:1": Aspect.V1x1,
    }
    return m.get(value.strip(), Aspect.V9x16)

def _parse_caption_position(value: str) -> CaptionPosition:
    m = {
        "Top": CaptionPosition.TOP,
        "Middle": CaptionPosition.MIDDLE,
        "Bottom": CaptionPosition.BOTTOM,
    }
    return m.get(value.strip(), CaptionPosition.BOTTOM)

def _parse_shorts_mode(value: str) -> ShortsMode:
    m = {
        "Off": ShortsMode.OFF,
        "Auto": ShortsMode.AUTO,
        "Force": ShortsMode.FORCE,
    }
    return m.get(value.strip(), ShortsMode.OFF)

def _build_config_from_json(data: Dict[str, Any]) -> Tuple[ProjectCfg, List[str]]:
    used_sources: List[str] = []
    # === audio ===
    segs = data.get("audioSegments", [])
    paths = [str(s.get("path", "")).strip() for s in segs if isinstance(s, dict) and s.get("path")]
    audio_basename = ""
    if paths:
        basenames = []
        for p in paths:
            b = _copy_file_to_assets(p)
            basenames.append(b)
            used_sources.append(p)
        audio_basename = _concatenate_audio_files(basenames)
    # === bg ===
    bg_path = str(data.get("bgPath", "")).strip()
    if bg_path:
        bg_basename = _copy_file_to_assets(bg_path)
        used_sources.append(bg_path)
    else:
        bg_basename = ""
    # === config root ===
    cr = data.get("config", {}) or data.get("visual", {})
    subs = (cr.get("subtitles") or cr.get("captions") or data.get("subtitles") or {}) or {}
    captions = CaptionCfg(
        font_choice=None,
        font_name=None,
        font_size=int(subs.get("fontSize", 92)),
        active_color=str(subs.get("primaryColor", "#FFFFFF")),
        keyword_color=str(subs.get("highlightColor", "#FFD700")),
        border_thickness=int(subs.get("outlineWidth", subs.get("border", 4))),
        max_words_per_line=int(subs.get("maxWordsPerLine", 6)),
        max_words_per_caption=int(subs.get("maxWordsPerCaption", 12)),
        position=_parse_caption_position(subs.get("position", "Bottom")),
        margin_v=int(subs.get("marginV", 70)),
    )
    vis = data.get("visual", {}) or cr
    asp = vis.get("aspect") or data.get("aspectRatio") or "9:16"
    ken = bool(vis.get("ken_burns", False))
    visual = VisualCfg(bg_image=bg_basename, aspect=_parse_aspect(asp), ken_burns=ken)
    aa = data.get("audio", {})
    audio = AudioCfg(
        filename=audio_basename,
        whisper_model=str(aa.get("whisperModel", "medium")),
        use_vad=bool(aa.get("useVad", True)),
        target_lufs=float(aa.get("targetLufs", -16.0)),
        target_lra=float(aa.get("targetLra", 11.0)),
        target_tp=float(aa.get("targetTp", -2.0)),
    )
    figures = FigureCfg(use=False, duration_s=1.8)
    intro_outro = IntroOutroCfg(intro_mp4=None, intro_key=False, outro_mp4=None, outro_key=False)
    cta = CTACfg(loop_mp4=None, start_s=0.0, repeat_s=0.0, key_color="#00FF00", similarity=0.23, blend=0.05, position=CaptionPosition.MIDDLE)
    bgm = BGMCfg(name=None, gain_db=-20.0, auto_duck=True, duck_threshold=-30.0, duck_ratio=12.0, duck_attack=20, duck_release=300)
    broll = BrollCfg(use=False, first_at=5.0, every_s=14.0, duration_s=4.0)
    sm = data.get("shorts", {}) or {}
    mode = sm.get("mode") or data.get("shortsMode", "Off")
    shorts = ShortsCfg(mode=_parse_shorts_mode(mode), min_s=int(sm.get("min_s", 45)), max_s=int(sm.get("max_s", 90)))
    cfg = ProjectCfg(
        audio=audio, captions=captions, figures=figures,
        intro_outro=intro_outro, cta=cta, bgm=bgm, broll=broll,
        visual=visual, shorts=shorts, dry_run=False, timestamp_offset=0.0
    )
    try:
        cfg = cfg.validate()
    except Exception as e:
        raise ValueError(f"تنظیمات نامعتبر: {e}") from e
    return cfg, used_sources

# ============ مدیریت Job Queue ============

JOBS_LOCK = threading.Lock()
JOBS: Dict[str, Dict[str, Any]] = {}

def _cleanup_old_jobs(max_jobs: int = 100) -> None:
    with JOBS_LOCK:
        if len(JOBS) <= max_jobs:
            return
        to_remove = list(JOBS.keys())[: len(JOBS) - max_jobs]
        for k in to_remove:
            JOBS.pop(k, None)

def _update_job(job_id: str, **fields: Any) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {"status": "queued", "progress": {"percentage": 0, "message": ""}})
        job.update(fields)

def _get_job_status(job_id: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        return dict(JOBS.get(job_id, {}))

def _render_worker(job_id: str, preset_json: Dict[str, Any]) -> None:
    try:
        _update_job(job_id, status="running", progress={"percentage": 5, "message": "آماده‌سازی..."})
        config, _sources = _build_config_from_json(preset_json)
        _update_job(job_id, progress={"percentage": 30, "message": "شروع رندر..."})
        renderer = Renderer(PATHS)
        output_file, norm_audio, filter_count, srt_path = renderer.render(config)
        video_name = Path(output_file).name
        video_url = f"/download?file={video_name}"
        _update_job(job_id, status="done", progress={"percentage": 100, "message": "اتمام"}, videoUrl=video_url)
    except Exception as e:
        log.exception("خطا در job رندر: %s", e)
        _update_job(job_id, status="error", error=str(e), progress={"percentage": 0, "message": "خطا رخ داد"})
    finally:
        _cleanup_old_jobs()

# ============ Flask App ============

app = Flask(__name__, static_folder="../frontend_dist", static_url_path="/")
CORS(app)

@app.get("/health")
def health_check() -> Any:
    return jsonify({"ok": True, "assets": str(PATHS.assets), "output_local": str(PATHS.out_local)}), 200

@app.get("/list-files")
def list_files_api() -> Any:
    path_str = (request.args.get("path") or "").strip()
    if not path_str:
        return jsonify({"error": "پارامتر path الزامی است"}), 400
    directory = Path(path_str).expanduser()
    if not directory.exists() or not directory.is_dir():
        return jsonify({"error": "PATH_NOT_FOUND_OR_NOT_DIR"}), 404
    # بررسی امنیت
    allowed_roots = [PATHS.assets, PATHS.out_local]
    if PATHS.base_drive:
        allowed_roots.append(PATHS.base_drive)
    def under_root(p: Path) -> bool:
        try:
            return p.resolve().is_relative_to(root.resolve())
        except Exception:
            rp = str(p.resolve())
            rr = str(root.resolve())
            return rp == rr or rp.startswith(rr + os.sep)
    items = []
    for ch in sorted(directory.iterdir(), key=lambda x: x.name.lower()):
        if any(under_root(ch, root) for root in allowed_roots):
            st = ch.stat()
            items.append({
                "name": ch.name,
                "type": "directory" if ch.is_dir() else "file",
                "size": 0 if ch.is_dir() else st.st_size,
                "mtime": int(st.st_mtime),
            })
    return jsonify(items), 200

@app.post("/transcribe")
def transcribe_api() -> Any:
    try:
        data = request.get_json(force=True)
        audio_paths = data.get("audioPaths") or []
        if not isinstance(audio_paths, list) or not audio_paths:
            return jsonify({"error": "audioPaths باید آرایه غیرخالی باشد"}), 400
        first = str(audio_paths[0]).strip()
        if not first:
            return jsonify({"error": "مسیر صوتی خالی است"}), 400
        basename = _copy_file_to_assets(first)
        scheduler = Scheduler()
        words = scheduler.transcribe_words(PATHS.assets / basename, size=str(data.get("model", "medium")), use_vad=bool(data.get("useVad", True)))
        transcript = " ".join(w.get("raw", "") for w in words).strip()
        return jsonify({"transcript": transcript}), 200
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        log.exception("خطا در رونویسی: %s", e)
        return jsonify({"error": str(e)}), 500

@app.post("/render")
def render_api() -> Any:
    try:
        data = request.get_json(force=True)
        job_id = uuid.uuid4().hex
        _update_job(job_id, status="queued", progress={"percentage": 1, "message": "در صف قرار گرفت"})
        threading.Thread(target=_render_worker, args=(job_id, data), daemon=True).start()
        return jsonify({"jobId": job_id}), 200
    except Exception as e:
        log.exception("خطا در ایجاد job: %s", e)
        return jsonify({"error": str(e)}), 500

@app.get("/status")
def status_api() -> Any:
    job_id = (request.args.get("jobId") or request.args.get("id") or "").strip()
    if not job_id:
        return jsonify({"error": "jobId الزامی است"}), 400
    job = _get_job_status(job_id)
    if not job:
        return jsonify({"error": "jobId یافت نشد"}), 404
    return jsonify(job), 200

@app.get("/download")
def download_api() -> Any:
    filename = (request.args.get("file") or "").strip()
    if not filename:
        return jsonify({"error": "پارامتر file الزامی است"}), 400
    # جلوگیری از path traversal
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return jsonify({"error": "نام فایل نامعتبر"}), 400
    file_path = PATHS.out_local / filename
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": "فایل خروجی پیدا نشد"}), 404
    return send_from_directory(PATHS.out_local, filename, as_attachment=False)

if __name__ == "__main__":
    os.makedirs(PATHS.out_local, exist_ok=True)
    host = os.getenv("VR_HOST", "0.0.0.0")
    port = int(os.getenv("VR_PORT", "8000"))
    log.info("🚀 VideoRobot HTTP Backend در %s:%d", host, port)
    app.run(host=host, port=port, debug=False)
