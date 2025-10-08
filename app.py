# /content/videorobot/app.py
# 🤖 VideoRobot Streamlit UI — works with your backend, no drama.

import os, sys, shutil, json, subprocess, time
from pathlib import Path
import streamlit as st

# ---------- Path setup so `import videorobot` works ----------
PKG_PARENT = Path(__file__).resolve().parents[1]  # /content
if str(PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(PKG_PARENT))
os.environ["PYTHONPATH"] = f"{PKG_PARENT}:{os.environ.get('PYTHONPATH','')}"

REPO_DIR   = Path("/content/videorobot")
DRIVE_BASE = Path("/content/drive/MyDrive/VideoRobot")
ASSETS_DIR = DRIVE_BASE / "Assets"
OUTPUT_DIR = DRIVE_BASE / "Output"
REPO_ASSETS = REPO_DIR / "Assets"
for p in [ASSETS_DIR, OUTPUT_DIR]:
    p.mkdir(parents=True, exist_ok=True)
# prefer Drive assets via symlink if repo lacks Assets
try:
    if not REPO_ASSETS.exists():
        os.symlink(str(ASSETS_DIR), str(REPO_ASSETS))
except Exception:
    pass

# ---------- Import backend (robust) ----------
Renderer = None
ProjectCfg = AudioCfg = CaptionCfg = VisualCfg = Aspect = CaptionPosition = ShortsCfg = None
Paths = IntroOutroCfg = CTACfg = BGMCfg = FigureCfg = BrollCfg = ShortsMode = None

def _try_imports():
    global Renderer, ProjectCfg, AudioCfg, CaptionCfg, VisualCfg, Aspect, CaptionPosition, ShortsCfg
    global Paths, IntroOutroCfg, CTACfg, BGMCfg, FigureCfg, BrollCfg, ShortsMode
    # Attempt 1: top-level package
    try:
        from videorobot import (
            Renderer as R, ProjectCfg as PC, AudioCfg as AC, CaptionCfg as CC,
            VisualCfg as VC, Aspect as ASP, CaptionPosition as CP, ShortsCfg as SC,
            Paths as PTH, IntroOutroCfg as IOC, CTACfg as CTC, BGMCfg as BG,
            FigureCfg as FGC, BrollCfg as BRC, ShortsMode as SM
        )
        Renderer, ProjectCfg, AudioCfg, CaptionCfg, VisualCfg = R, PC, AC, CC, VC
        Aspect, CaptionPosition, ShortsCfg = ASP, CP, SC
        Paths, IntroOutroCfg, CTACfg, BGMCfg = PTH, IOC, CTC, BG
        FigureCfg, BrollCfg, ShortsMode = FGC, BRC, SM
        return True
    except Exception:
        pass
    # Attempt 2: module-style
    try:
        from videorobot.renderer import Renderer as R
        Renderer = R
    except Exception:
        pass
    try:
        import videorobot.config as cfg
        ProjectCfg = getattr(cfg, "ProjectCfg", None)
        AudioCfg   = getattr(cfg, "AudioCfg", None)
        CaptionCfg = getattr(cfg, "CaptionCfg", None)
        VisualCfg  = getattr(cfg, "VisualCfg", None)
        Aspect     = getattr(cfg, "Aspect", None)
        CaptionPosition = getattr(cfg, "CaptionPosition", None)
        ShortsCfg  = getattr(cfg, "ShortsCfg", None)
        Paths      = getattr(cfg, "Paths", None)
        IntroOutroCfg = getattr(cfg, "IntroOutroCfg", None)
        CTACfg     = getattr(cfg, "CTACfg", None)
        BGMCfg     = getattr(cfg, "BGMCfg", None)
        FigureCfg  = getattr(cfg, "FigureCfg", None)
        BrollCfg   = getattr(cfg, "BrollCfg", None)
        ShortsMode = getattr(cfg, "ShortsMode", None)
    except Exception:
        pass
    # Attempt 3: backend package duplicates
    if Renderer is None:
        try:
            from videorobot.backend.renderer import Renderer as R
            Renderer = R
        except Exception:
            pass
    if CaptionCfg is None:
        try:
            import videorobot.backend.config as bcfg
            CaptionCfg = getattr(bcfg, "CaptionCfg", CaptionCfg)
            ProjectCfg = getattr(bcfg, "ProjectCfg", ProjectCfg)
            AudioCfg   = getattr(bcfg, "AudioCfg",   AudioCfg)
            VisualCfg  = getattr(bcfg, "VisualCfg",  VisualCfg)
            Aspect     = getattr(bcfg, "Aspect",     Aspect)
            CaptionPosition = getattr(bcfg, "CaptionPosition", CaptionPosition)
            ShortsCfg  = getattr(bcfg, "ShortsCfg",  ShortsCfg)
            Paths      = getattr(bcfg, "Paths",      Paths)
            IntroOutroCfg = getattr(bcfg, "IntroOutroCfg", IntroOutroCfg)
            CTACfg     = getattr(bcfg, "CTACfg",     CTACfg)
            BGMCfg     = getattr(bcfg, "BGMCfg",     BGMCfg)
            FigureCfg  = getattr(bcfg, "FigureCfg",  FigureCfg)
            BrollCfg   = getattr(bcfg, "BrollCfg",   BrollCfg)
            ShortsMode = getattr(bcfg, "ShortsMode", ShortsMode)
        except Exception:
            pass
    return any([Renderer, ProjectCfg, AudioCfg, CaptionCfg, VisualCfg])

_import_ok = _try_imports()

# ---------- CaptionCfg compatibility shim ----------
# Handles API drift: adds new required params if missing, maps font_name -> font_choice.
import inspect as _inspect
def make_caption_cfg(**kw):
    if CaptionCfg is None:
        raise RuntimeError("CaptionCfg not found in backend.")
    sig = _inspect.signature(CaptionCfg)
    allowed = set(sig.parameters.keys())
    # map old->new
    if "font_name" in kw and "font_choice" in allowed and "font_choice" not in kw:
        kw["font_choice"] = kw.pop("font_name")
    # safe defaults for newer API
    defaults = dict(border_thickness=2, max_words_per_line=6, max_words_per_caption=32)
    for k, v in defaults.items():
        if k in allowed and k not in kw:
            kw[k] = v
    clean = {k: v for k, v in kw.items() if k in allowed}
    return CaptionCfg(**clean)

# ---------- UI ----------
st.set_page_config(page_title="VideoRobot", layout="wide")
st.title("🤖 VideoRobot: رابط رندر")

if not _import_ok:
    st.error("ماژول‌های بک‌اند پیدا نشدند. ساختار ریپو را چک کن. حداقل یکی از این‌ها لازم است: "
             "`videorobot/renderer.py` یا `videorobot/backend/renderer.py` و `config.py`.")
    st.stop()

# Sidebar: pick assets from Google Drive
with st.sidebar:
    st.header("📁 فایل‌ها از Google Drive")
    def list_files(dir_path: Path, exts: set):
        if not dir_path.exists(): return []
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

st.header("⚙️ تنظیمات")
col1, col2 = st.columns(2)
with col1:
    aspect_ratio = st.selectbox("نسبت تصویر", ['9:16', '1:1', '16:9'], index=0)
    ken_burns    = st.checkbox("افکت زوم (Ken Burns)", value=True)
    font_size    = st.slider("اندازه فونت", 30, 150, 92)
    whisper_model= st.selectbox("مدل Whisper", ['tiny', 'base', 'small', 'medium', 'large'], index=2)
with col2:
    active_color  = st.color_picker("رنگ اصلی زیرنویس", "#FFFFFF")
    keyword_color = st.color_picker("رنگ کلمات کلیدی", "#FFD700")
    caption_pos   = st.selectbox("موقعیت زیرنویس", ['BOTTOM', 'MIDDLE', 'TOP'], index=0)
    use_vad       = st.checkbox("Voice Activity Detection", value=True)

def _aspect(val):
    if Aspect is None: return None
    return {'9:16': Aspect.V9x16, '1:1': Aspect.V1x1, '16:9': Aspect.V16x9}.get(val, Aspect.V9x16)

def _cap_pos(val):
    if CaptionPosition is None: return None
    return {'TOP': CaptionPosition.TOP, 'MIDDLE': CaptionPosition.MIDDLE, 'BOTTOM': CaptionPosition.BOTTOM}.get(val, CaptionPosition.BOTTOM)

def run_render():
    # Guard inputs
    if "(هیچی نیست)" in [audio_file, bg_image]:
        st.error("لطفاً فایل صوتی و تصویر پس‌زمینه را انتخاب کن.")
        return

    chosen_font_name = "DejaVu Sans" if font_file == "(پیش‌فرض)" else Path(font_file).stem

    # Strategy A: full config API exists
    if all([ProjectCfg, AudioCfg, VisualCfg, Paths, Renderer]):
        try:
            captions = make_caption_cfg(
                font_choice=chosen_font_name,  # shim handles both old/new
                font_size=font_size,
                active_color=active_color,
                keyword_color=keyword_color,
                position=_cap_pos(caption_pos),
                margin_v=70
            )
            config = ProjectCfg(
                audio=AudioCfg(filename=audio_file, whisper_model=whisper_model, use_vad=use_vad),
                captions=captions,
                figures=FigureCfg(use=False) if FigureCfg else None,
                intro_outro=IntroOutroCfg(
                    intro_mp4=None if intro_file=="(ندارم)" else intro_file,
                    outro_mp4=None if outro_file=="(ندارم)" else outro_file
                ) if IntroOutroCfg else None,
                cta=CTACfg(loop_mp4=None if cta_file=="(ندارم)" else cta_file) if CTACfg else None,
                bgm=BGMCfg(name=None if bgm_file=="(ندارم)" else bgm_file) if BGMCfg else None,
                broll=BrollCfg(use=False) if BrollCfg else None,
                visual=VisualCfg(bg_image=bg_image, aspect=_aspect(aspect_ratio), ken_burns=ken_burns),
                shorts=ShortsCfg(mode=ShortsMode.AUTO) if ShortsCfg and ShortsMode else None,
            )
            # remove None fields if dataclass enforces
            if hasattr(config, "__dict__"):
                cfgd = {k: v for k, v in config.__dict__.items() if v is not None}
                config = ProjectCfg(**cfgd) if type(config) is not ProjectCfg else config

            paths = Paths(
                base_local=REPO_DIR, base_drive=DRIVE_BASE,
                tmp=REPO_DIR / "_vr_tmp",
                out_local=REPO_DIR / "_vr_out",
                out_drive=OUTPUT_DIR,
                assets=ASSETS_DIR, figures=ASSETS_DIR / "Figures",
                music=ASSETS_DIR / "Music",
                broll=DRIVE_BASE / "Broll",
            )
            if hasattr(paths, "ensure_dirs"): paths.ensure_dirs()
            renderer = Renderer(paths)
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
                shutil.copy2(output_video, final_path)
                st.success("✅ ویدیو با موفقیت ساخته شد!")
                st.video(str(final_path))
                st.markdown(f"مسیر فایل: `{final_path}`")
            return
        except Exception as e:
            st.warning(f"مسیر A شکست خورد: {e}. می‌رویم سراغ مسیر B...")

    # Strategy B: simple Renderer interface
    if Renderer is not None:
        try:
            r = Renderer()  # many codebases allow simple init
            with st.spinner("در حال رندر (مسیر B)..."):
                out = r.render(
                    audio_file=audio_file,
                    bg_image=bg_image,
                    output_dir=str(OUTPUT_DIR),
                    font_name=chosen_font_name,
                    font_size=font_size,
                    active_color=active_color,
                    keyword_color=keyword_color,
                    ken_burns=ken_burns,
                    aspect=str(aspect_ratio)
                )
                if isinstance(out, (list, tuple)) and len(out) > 0:
                    output_video = out[0]
                else:
                    output_video = out if isinstance(out, (str, Path)) else None
                if output_video:
                    st.success("✅ ویدیو با موفقیت ساخته شد! (B)")
                    st.video(str(output_video))
                    return
        except Exception as e:
            st.warning(f"مسیر B شکست خورد: {e}. می‌رویم سراغ مسیر C...")

    # Strategy C: run main.py as a subprocess
    main_py = REPO_DIR / "main.py"
    if main_py.exists():
        try:
            cmd = [
                "python", str(main_py),
                "--audio", str(ASSETS_DIR / audio_file),
                "--bg", str(ASSETS_DIR / bg_image),
                "--out", str(OUTPUT_DIR),
                "--font", chosen_font_name,
                "--font_size", str(font_size),
                "--active_color", str(active_color),
                "--keyword_color", str(keyword_color),
                "--aspect", aspect_ratio,
            ]
            with st.spinner("در حال رندر توسط main.py ..."):
                proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
                st.text(proc.stdout[-2000:])
            # try to show latest mp4 from output
            outs = sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if outs:
                st.success("✅ ویدیو ساخته شد! (C)")
                st.video(str(outs[0]))
                return
            st.error("main.py اجرا شد ولی فایل خروجی پیدا نشد.")
        except Exception as e:
            st.error(f"مسیر C هم شکست خورد: {e}")
            return
    else:
        st.error("main.py وجود ندارد و API رندر هم پیدا نشد.")

if st.button("🎬 شروع رندر"):
    run_render()
