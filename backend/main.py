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
import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from flask import Flask, request, jsonify
from flask_cors import CORS

# بخش داخلی
from .config import Paths, ProjectCfg, AudioCfg, CaptionCfg, FigureCfg, IntroOutroCfg, CTACfg, BGMCfg, BrollCfg, VisualCfg, ShortsCfg, Aspect, CaptionPosition, ShortsMode, FONTS
from utils import docs_guard, mount_drive_once, resolve_drive_base
from renderer_service import renderer_bp, RendererQueue

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

renderer_queue = RendererQueue(paths=PATHS)

# ============ Flask App ============

app = Flask(__name__, static_folder="../frontend_dist", static_url_path="/")


def _resolve_allowed_origins() -> List[str]:
    raw = os.getenv("CORS_ALLOW_ORIGIN", "")
    origins = {o.strip() for o in raw.split(",") if o.strip()}
    tunnel = os.getenv("CF_TUNNEL_HOSTNAME", "").strip()
    if tunnel:
        if tunnel.startswith("http://") or tunnel.startswith("https://"):
            origins.add(tunnel)
        else:
            origins.add(f"https://{tunnel}")
    if not origins:
        origins.update({"http://127.0.0.1:5173", "http://localhost:5173"})
    return sorted(origins)


CORS(app, resources={r"/*": {"origins": _resolve_allowed_origins()}})
app.register_blueprint(renderer_bp)


def _response_ok(data: Any, status_code: int = 200):
    payload = {"ok": True, "data": data, "error": None}
    return jsonify(payload), status_code


def _response_error(message: str, status_code: int):
    payload = {"ok": False, "data": None, "error": message}
    return jsonify(payload), status_code

@app.get("/health")
def health_check() -> Any:
    data = {
        "assets": str(PATHS.assets),
        "output_local": str(PATHS.out_local),
    }
    return _response_ok(data)


@app.get("/healthz")
def healthz() -> Any:
    return health_check()


@app.get("/version")
def version_info() -> Any:
    data = {
        "version": os.getenv("VR_VERSION", "0.0.0"),
        "git": os.getenv("GIT_COMMIT", "unknown"),
    }
    return _response_ok(data)

@app.get("/list-files")
def list_files_api() -> Any:
    path_str = (request.args.get("path") or "").strip()
    if not path_str:
        return _response_error("پارامتر path الزامی است", 400)
    directory = Path(path_str).expanduser()
    if not directory.exists() or not directory.is_dir():
        return _response_error("PATH_NOT_FOUND_OR_NOT_DIR", 404)
    # بررسی امنیت
    allowed_roots = [PATHS.assets, PATHS.out_local]
    if PATHS.base_drive:
        allowed_roots.append(PATHS.base_drive)

    def under_root(p: Path, root: Path) -> bool:
        resolved_root = root.resolve()
        resolved_path = p.resolve()
        return resolved_path == resolved_root or resolved_root in resolved_path.parents
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
    return _response_ok({"items": items})

@app.post("/transcribe")
def transcribe_api() -> Any:
    try:
        data = request.get_json(force=True)
        audio_paths = data.get("audioPaths") or []
        if not isinstance(audio_paths, list) or not audio_paths:
            return _response_error("audioPaths باید آرایه غیرخالی باشد", 400)
        first = str(audio_paths[0]).strip()
        if not first:
            return _response_error("مسیر صوتی خالی است", 400)
        basename = _copy_file_to_assets(first)
        scheduler = Scheduler()
        words = scheduler.transcribe_words(PATHS.assets / basename, size=str(data.get("model", "medium")), use_vad=bool(data.get("useVad", True)))
        transcript = " ".join(w.get("raw", "") for w in words).strip()
        return _response_ok({"transcript": transcript})
    except FileNotFoundError as e:
        return _response_error(str(e), 404)
    except Exception as e:
        log.exception("خطا در رونویسی: %s", e)
        return _response_error(str(e), 500)

if __name__ == "__main__":
    os.makedirs(PATHS.out_local, exist_ok=True)
    host = os.getenv("VR_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", os.getenv("VR_PORT", "8000")))
    log.info("🚀 VideoRobot HTTP Backend در %s:%d", host, port)
    app.run(host=host, port=port, debug=False)
