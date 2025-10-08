# /content/videorobot/app.py
# -*- coding: utf-8 -*-
# 🤖 VideoRobot Streamlit UI — stable imports, backend-first, robust render paths.

import os
import sys
import shutil
import subprocess
from pathlib import Path
import inspect as _inspect
import streamlit as st

# ---------- Path setup so `import videorobot` works ----------
PKG_PARENT = Path(__file__).resolve().parents[1]  # /content
if str(PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(PKG_PARENT))
os.environ["PYTHONPATH"] = f"{PKG_PARENT}:{os.environ.get('PYTHONPATH','')}"

# ---------- Constants & Paths ----------
REPO_DIR    = Path("/content/videorobot")
DRIVE_BASE  = Path("/content/drive/MyDrive/VideoRobot")
ASSETS_DIR  = DRIVE_BASE / "Assets"
OUTPUT_DIR  = DRIVE_BASE / "Output"
REPO_ASSETS = REPO_DIR / "Assets"

for p in [ASSETS_DIR, OUTPUT_DIR]:
    p.mkdir(parents=True, exist_ok=True)

# Prefer Drive assets via symlink if repo lacks Assets
try:
    if not REPO_ASSETS.exists():
        os.symlink(str(ASSETS_DIR), str(REPO_ASSETS))
except FileExistsError:
    pass
except Exception:
    pass

# ---------- Import backend (explicit-first, robust-fallback) ----------
Renderer = None
ProjectCfg = AudioCfg = CaptionCfg = VisualCfg = Aspect = CaptionPosition = ShortsCfg = None
Paths = IntroOutroCfg = CTACfg = BGMCfg = FigureCfg = BrollCfg = ShortsMode = None

_backend_error = None

def _import_backend():
    """Prefer videorobot.backend.*, fallback to videorobot.* legacy."""
    global Renderer, ProjectCfg, AudioCfg, CaptionCfg, VisualCfg, Aspect, CaptionPosition, ShortsCfg
    global Paths, IntroOutroCfg, CTACfg, BGMCfg, FigureCfg, BrollCfg, ShortsMode, _backend_error

    # Attempt A: backend/*
    try:
        from videorobot.backend.renderer import Renderer as _R
        from videorobot.backend.config import (
            ProjectCfg as _PC, AudioCfg as _AC, CaptionCfg as _CC, VisualCfg as _VC,
            Aspect as _ASP, CaptionPosition as _CP, ShortsCfg as _SC, Paths as _PTH,
            IntroOutroCfg as _IOC, CTACfg as _CTC, BGMCfg as _BG, FigureCfg as _FGC,
            BrollCfg as _BRC, ShortsMode as _SM
        )
        Renderer, ProjectCfg, AudioCfg, CaptionCfg, VisualCfg = _R, _PC, _AC, _CC, _VC
        Aspect, CaptionPosition, ShortsCfg = _ASP, _CP, _SC
        Paths, IntroOutroCfg, CTACfg, BGMCfg = _PTH, _IOC, _CTC, _BG
        FigureCfg, BrollCfg, ShortsMode = _FGC, _BRC, _SM
        return True
    except Exception as e:
        _backend_error = f"backend import failed: {e}"

    # Attempt B: legacy root modules
    try:
        from videorobot.renderer import Renderer as _R
        import videorobot.config as _cfg
        Renderer = _R
        ProjectCfg        = getattr(_cfg, "ProjectCfg", None)
        AudioCfg          = getattr(_cfg, "AudioCfg", None)
        CaptionCfg        = getattr(_cfg, "CaptionCfg", None)
        VisualCfg         = getattr(_cfg, "VisualCfg", None)
        Aspect            = getattr(_cfg, "Aspect", None)
        CaptionPosition   = getattr(_cfg, "CaptionPosition", None)
        ShortsCfg         = getattr(_cfg, "ShortsCfg", None)
        Paths             = getattr(_cfg, "Paths", None)
        IntroOutroCfg     = getattr(_cfg, "IntroOutroCfg", None)
        CTACfg            = getattr(_cfg, "CTACfg", None)
        BGMCfg            = getattr(_cfg, "BGMCfg", None)
        FigureCfg         = getattr(_cfg, "FigureCfg", None)
        BrollCfg          = getattr(_cfg, "BrollCfg", None)
        ShortsMode        = getattr(_cfg, "ShortsMode", None)
        return any([Renderer, ProjectCfg, AudioCfg, CaptionCfg, VisualCfg])
    except Exception as e:
        _backend_error = f"{_backend_error or ''} | root import failed: {e}"
        return False

_import_ok = _import_backend()

# ---------- CaptionCfg compatibility shim ----------
def make_caption_cfg(**kw):
    """
    Harmonize CaptionCfg args across versions:
    - Accepts font_name or font_choice (maps as needed)
    - Supplies safe defaults when newer required args exist
    """
    if CaptionCfg is None:
        raise RuntimeError("CaptionCfg not available in backend.")

    sig = _inspect.signature(CaptionCfg)
    allowed = set(sig.parameters.keys())

    # font normalization
    fname = kw.pop("font_name", None)
    fchoice = kw.pop("font_choice", None)
    font_val = fchoice or fname
    if "font_choice" in allowed and "font_choice" not in kw and font_val is not None:
        kw["font_choice"] = font_val
    if "font_name" in allowed and "font_name" not in kw and font_val is not None:
        kw["font_name"] = font_val

    # safe defaults for newer params if present
    defaults = dict(border_thickness=2, max_words_per_line=6, max_words_per_caption=32, margin_v=70)
    for k, v in defaults.items():
        if k in allowed and k not in kw:
            kw[k] = v

    # filter unknown keys
    clean = {k: v for k, v in kw.items() if k in allowed}
    return CaptionCfg(**clean)

# ---------- FigureCfg compatibility shim ----------
def make_figure_cfg(**kw):
    """
    Provide safe defaults for FigureCfg across versions.
    Many codebases require: use, duration_s, appear_after_s, hold_s, fade_s.
    """
    if FigureCfg is None:
        return None  # If project allows figures=None, that's fine

    sig = _inspect.signature(FigureCfg)
    allowed = set(sig.parameters.keys())

    defaults = dict(
        use=False,
        duration_s=0.0,
        appear_after_s=0.0,
        hold_s=0.0,
        fade_s=0.2,
    )
    for k, v in defaults.items():
        if k in allowed and k not in kw:
            kw[k] = v

    clean = {k: v for k, v in kw.items() if k in allowed}
    return FigureCfg(**clean)

# ---------- UI ----------
st.set_page_config(page_title="VideoRobot", layout="wide")
st.title("🤖 VideoRobot: رابط رندر")

if not _import_ok or not all([Renderer, ProjectCfg, AudioCfg, CaptionCfg, VisualCfg, Paths]):
    st.error(
        "ماژول‌های بک‌اند پیدا نشدند یا ناقص‌اند.\n"
        "حداقل این فایل‌ها لازم‌اند:\n"
        "• videorobot/backend/config.py\n"
        "• videorobot/backend/renderer.py\n"
        f"جزئیات: {_backend_error or 'N/A'}"
    )
    st.stop()

# ---------- Sidebar: pick assets from Google Drive ----------
with st.sidebar:
    st.header("📁 فایل‌ها از Google Drive")

    def list_files(dir_path: Path, exts: set[str]):
        if not dir_path.exists():
            return []
        return [f.name for f in sorted(dir_path.glob("*")) if f.is_file() and f.suffix.lower() in exts]

    audio_files = list_files(ASSETS_DIR, {".mp3", ".wav", ".m4a"})
    image_files = list_files(ASSETS_DIR, {".jpg", ".jpeg", ".png"})
    font_files  = list_files(ASSETS_DIR / "Fonts", {".ttf", ".otf"})
    intro_files = list_files(ASSETS_DIR / "Intro", {".mp4", ".mov"})
    outro_files = list_files(ASSETS_DIR / "Outro", {".mp4", ".mov"})
    cta_files   = list_files(ASSETS_DIR / "CTA", {".mp4", ".mov"})
    bgm_files   = list_files(ASSETS_DIR / "Music", {".mp3", ".wav", ".m4a"})

    audio_file = st.selectbox("🎧 فایل صوتی", options=audio_files or ["(هیچی نیست)"])
    bg_image   = st.selectbox("🖼️ تصویر پس‌زمینه", options=image_files or ["(هیچی نیست)"])
    font_file  = st.selectbox("🔤 فونت (اختیاری)", options=["(پیش‌فرض)"] + font_files)
    intro_file = st.selectbox("🎬 Intro", options=["(ندارم)"] + intro_files)
    outro_file = st.selectbox("🏁 Outro", options=["(ندارم)"] + outro_files)
    cta_file   = st.selectbox("🔁 CTA Loop", options=["(ندارم)"] + cta_files)
    bgm_file   = st.selectbox("🎵 موسیقی پس‌زمینه", options=["(ندارم)"] + bgm_files)

# ---------- Controls ----------
st.header("⚙️ تنظیمات")
col1, col2 = st.columns(2)
with col1:
    aspect_ratio  = st.selectbox("نسبت تصویر", ['9:16', '1:1', '16:9'], index=0)
    ken_burns     = st.checkbox("افکت زوم (Ken Burns)", value=True)
    font_size     = st.slider("اندازه فونت", 30, 150, 92)
    whisper_model = st.selectbox("مدل Whisper", ['tiny', 'base', 'small', 'medium', 'large'], index=2)
with col2:
    active_color  = st.color_picker("رنگ اصلی زیرنویس", "#FFFFFF")
    keyword_color = st.color_picker("رنگ کلمات کلیدی", "#FFD700")
    caption_pos   = st.selectbox("موقعیت زیرنویس", ['BOTTOM', 'MIDDLE', 'TOP'], index=0)
    use_vad       = st.checkbox("Voice Activity Detection", value=True)

def _aspect(val):
    if Aspect is None:
        return None
    return {'9:16': Aspect.V9x16, '1:1': Aspect.V1x1, '16:9': Aspect.V16x9}.get(val, Aspect.V9x16)

def _cap_pos(val):
    if CaptionPosition is None:
        return None
    return {'TOP': CaptionPosition.TOP, 'MIDDLE': CaptionPosition.MIDDLE, 'BOTTOM': CaptionPosition.BOTTOM}.get(val, CaptionPosition.BOTTOM)

# ---------- Render Action ----------
def run_render():
    if "(هیچی نیست)" in [audio_file, bg_image]:
        st.error("لطفاً فایل صوتی و تصویر پس‌زمینه را انتخاب کن.")
        return

    chosen_font_name = "DejaVu Sans" if font_file == "(پیش‌فرض)" else Path(font_file).stem

    try:
        captions = make_caption_cfg(
            font_name=chosen_font_name,        # shim will map/allow font_choice too
            font_size=font_size,
            active_color=active_color,
            keyword_color=keyword_color,
            position=_cap_pos(caption_pos),
            margin_v=70
        )

        config = ProjectCfg(
            audio=AudioCfg(filename=audio_file, whisper_model=whisper_model, use_vad=use_vad),
            captions=captions,
            figures=make_figure_cfg(use=False) if FigureCfg else None,
            intro_outro=IntroOutroCfg(
                intro_mp4=None if intro_file == "(ندارم)" else intro_file,
                outro_mp4=None if outro_file == "(ندارم)" else outro_file
            ) if IntroOutroCfg else None,
            cta=CTACfg(loop_mp4=None if cta_file == "(ندارم)" else cta_file) if CTACfg else None,
            bgm=BGMCfg(name=None if bgm_file == "(ندارم)" else bgm_file) if BGMCfg else None,
            broll=BrollCfg(use=False) if BrollCfg else None,
            visual=VisualCfg(bg_image=bg_image, aspect=_aspect(aspect_ratio), ken_burns=ken_burns),
            shorts=ShortsCfg(mode=ShortsMode.AUTO) if ShortsCfg and ShortsMode else None,
        )

        paths = Paths(
            base_local=REPO_DIR,
            base_drive=DRIVE_BASE,
            tmp=REPO_DIR / "_vr_tmp",
            out_local=REPO_DIR / "_vr_out",
            out_drive=OUTPUT_DIR,
            assets=ASSETS_DIR,
            figures=ASSETS_DIR / "Figures",
            music=ASSETS_DIR / "Music",
            broll=DRIVE_BASE / "Broll",
        )
        if hasattr(paths, "ensure_dirs"):
            paths.ensure_dirs()

        renderer = Renderer(paths)  # Renderer.__init__(paths) -> None

        with st.spinner("در حال رندر..."):
            out = renderer.render(config)
            # accept multiple return shapes
            if isinstance(out, (list, tuple)) and len(out) > 0:
                output_video = out[0]
            else:
                output_video = out if isinstance(out, (str, Path)) else None

            if not output_video:
                st.warning("رندر انجام شد اما مسیر خروجی مشخص نشد.")
                return

            output_video = Path(output_video)
            final_path = OUTPUT_DIR / output_video.name
            try:
                shutil.copy2(output_video, final_path)
            except Exception:
                # if already placed in OUTPUT_DIR
                final_path = output_video if output_video.exists() else final_path

            st.success("✅ ویدیو با موفقیت ساخته شد!")
            st.video(str(final_path))
            st.markdown(f"مسیر فایل: `{final_path}`")
    except Exception as e:
        st.error(f"❌ خطا هنگام رندر: {e}")

if st.button("🎬 شروع رندر", type="primary", use_container_width=True):
    run_render()
