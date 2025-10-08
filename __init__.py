# -*- coding: utf-8 -*-
"""
VideoRobot — Package Initializer (Full Edition)

این ماژول وظیفه‌ی مقداردهی اولیه پکیج را برعهده دارد:
- تشخیص نسخه از متادیتا با fallback
- تنظیم استراتژی ایمپورت: اولویت با videorobot/backend/*، سپس سقوط به ریشه
- تعریف API عمومی (__all__)
- راه‌اندازی logging با اولویت استفاده از utils.setup_logging
- گزارش خطای شفاف اگر چیدمان پروژه ناقص باشد
- شیم سازگاری سبک برای تفاوت امضای CaptionCfg بین نسخه‌ها (اختیاری)

ساختارهای پشتیبانی‌شده:
1) پیشنهاد‌شده (جدید):
   videorobot/
     ├── backend/
     │   ├── config.py
     │   ├── renderer.py
     │   ├── utils.py
     │   ├── scheduler.py
     │   ├── subtitles.py
     │   └── audio_processor.py
     └── __init__.py

2) قدیمی (fallback):
   videorobot/
     ├── config.py
     ├── renderer.py
     ├── utils.py
     ├── scheduler.py
     ├── subtitles.py
     └── audio_processor.py
"""

from __future__ import annotations

# ===========================================================================
# SECTION 0: Imports and typing
# ===========================================================================
from importlib import metadata
import logging
import os
from typing import Optional, Iterable, Any, Dict

# ===========================================================================
# SECTION 1: Version detection with fallback
# ===========================================================================
def _detect_version(package_name: str = "videorobot", fallback: str = "1.0.0") -> str:
    """
    تلاش برای خواندن نسخه از متادیتای نصب پکیج.
    اگر یافت نشد (حالت توسعه/Editable)، نسخه‌ی fallback برگردانده می‌شود.
    """
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return fallback

__version__ = _detect_version()

# ===========================================================================
# SECTION 2: Import strategy (prefer backend/*, fallback to root)
# ===========================================================================
# پرچم‌ها برای گزارش وضعیت ایمپورت
_BACKEND_OK: bool = False
_BACKEND_ERR: str | None = None
_ROOT_OK: bool = False
_ROOT_ERR: str | None = None

# امضاهای عمومی که انتظار داریم در API ارائه شوند
# توجه: اینجا فقط نام‌ها هستند. خود آبجکت‌ها بعداً ایمپورت می‌شوند.
__all__ = [
    # Config layer
    "Paths", "ProjectCfg", "AudioCfg", "CaptionCfg", "FigureCfg", "IntroOutroCfg",
    "CTACfg", "BGMCfg", "BrollCfg", "VisualCfg", "ShortsCfg",
    "Aspect", "CaptionPosition", "ShortsMode", "FONTS",
    # Core classes
    "Renderer", "Scheduler", "SubtitleWriter", "AudioProcessor",
    # Utilities
    "sh", "setup_logging", "sanitize_filename", "hex_to_0xRRGGBB",
    "srt_time", "hhmmss_cs", "build_fonts_only", "pick_default_font_name",
    "mount_drive_once", "resolve_drive_base", "sync_from_drive_to_local",
    "ensure_pkg_safe", "docs_guard",
    # Variables
    "__version__",
    # Optional helpers
    "make_caption_cfg_compat",  # شیم سازگاری CaptionCfg
]

# ابتدا تلاش برای ایمپورت از backend/*
try:
    from .backend.config import (
        Paths, ProjectCfg, AudioCfg, CaptionCfg, FigureCfg, IntroOutroCfg,
        CTACfg, BGMCfg, BrollCfg, VisualCfg, ShortsCfg,
        Aspect, CaptionPosition, ShortsMode, FONTS,
    )
    from .backend.renderer import Renderer
    from .backend.scheduler import Scheduler
    from .backend.subtitles import SubtitleWriter
    from .backend.audio_processor import AudioProcessor
    from .backend.utils import (
        sh, setup_logging, sanitize_filename, hex_to_0xRRGGBB,
        srt_time, hhmmss_cs, build_fonts_only, pick_default_font_name,
        mount_drive_once, resolve_drive_base, sync_from_drive_to_local,
        ensure_pkg_safe, docs_guard,
    )
    _BACKEND_OK = True
except Exception as _e_backend:
    _BACKEND_ERR = f"{type(_e_backend).__name__}: {_e_backend}"
    # سقوط به ساختار قدیمی ریشه
    try:
        from .config import (
            Paths, ProjectCfg, AudioCfg, CaptionCfg, FigureCfg, IntroOutroCfg,
            CTACfg, BGMCfg, BrollCfg, VisualCfg, ShortsCfg,
            Aspect, CaptionPosition, ShortsMode, FONTS,
        )
        from .renderer import Renderer
        from .scheduler import Scheduler
        from .subtitles import SubtitleWriter
        from .audio_processor import AudioProcessor
        from .utils import (
            sh, setup_logging, sanitize_filename, hex_to_0xRRGGBB,
            srt_time, hhmmss_cs, build_fonts_only, pick_default_font_name,
            mount_drive_once, resolve_drive_base, sync_from_drive_to_local,
            ensure_pkg_safe, docs_guard,
        )
        _ROOT_OK = True
    except Exception as _e_root:
        _ROOT_ERR = f"{type(_e_root).__name__}: {_e_root}"
        # گزارش خطای شفاف و قابل‌درک
        _msg = (
            "VideoRobot import failed.\n\n"
            "Neither 'videorobot/backend/*' nor legacy root modules are importable.\n"
            "Make sure your repository contains either:\n"
            "  - videorobot/backend/config.py AND videorobot/backend/renderer.py  (recommended)\n"
            "    plus utils.py, scheduler.py, subtitles.py, audio_processor.py\n"
            "OR\n"
            "  - videorobot/config.py AND videorobot/renderer.py (legacy layout)\n\n"
            "Also ensure '__init__.py' exists in both 'videorobot/' and 'videorobot/backend/'.\n"
            f"Backend error: {_BACKEND_ERR}\n"
            f"Root error:    {_ROOT_ERR}\n"
        )
        raise ImportError(_msg) from _e_root

# ===========================================================================
# SECTION 3: Optional compatibility shim for CaptionCfg
# ===========================================================================
def make_caption_cfg_compat(**kwargs) -> CaptionCfg:
    """
    شیم سازگاری برای سازندۀ CaptionCfg در نسخه‌های مختلف:
    - برخی نسخه‌ها 'font_name' می‌خواهند.
    - برخی دیگر 'font_choice' دارند.
    - پارامترهای جدیدی مثل border_thickness، max_words_per_line، max_words_per_caption
      اگر در امضا باشند ولی کاربر ندهد، با دیفالت‌های امن پر می‌شود.

    استفاده:
        captions = make_caption_cfg_compat(
            font_name="IRANSans",   # یا font_choice
            font_size=92,
            active_color="#FFFFFF",
            keyword_color="#FFD700",
            position=CaptionPosition.BOTTOM,
            margin_v=70,
        )
    """
    import inspect
    sig = inspect.signature(CaptionCfg)
    allowed = set(sig.parameters.keys())

    # normalize font args
    fname = kwargs.pop("font_name", None)
    fchoice = kwargs.pop("font_choice", None)
    font_val = fchoice or fname

    if "font_name" in allowed and "font_name" not in kwargs and font_val is not None:
        kwargs["font_name"] = font_val
    if "font_choice" in allowed and "font_choice" not in kwargs and font_val is not None:
        kwargs["font_choice"] = font_val

    # sensible defaults for newer params if present in signature
    defaults = dict(
        border_thickness=2,
        max_words_per_line=6,
        max_words_per_caption=32,
        margin_v=kwargs.get("margin_v", 70),
    )
    for k, v in defaults.items():
        if k in allowed and k not in kwargs:
            kwargs[k] = v

    # filter unknown keys
    clean = {k: v for k, v in kwargs.items() if k in allowed}

    return CaptionCfg(**clean)  # type: ignore[arg-type]

# ===========================================================================
# SECTION 4: Logging bootstrap (single source of truth via utils.setup_logging)
# ===========================================================================
def _bootstrap_logger() -> logging.Logger:
    """
    تلاش برای راه‌اندازی لاگر از utils.setup_logging؛ اگر نبود/خراب بود،
    به basicConfig با فرمت قابل‌خواندن سقوط می‌کنیم.
    """
    try:
        # سطح لاگ را از env بخوان (پیش‌فرض INFO)
        level_env = os.getenv("VIDEO_ROBOT_LOG_LEVEL", "INFO")
        return setup_logging(level=level_env)  # from utils
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        return logging.getLogger("VideoRobot")

log = _bootstrap_logger()
log.debug(
    "VideoRobot imported (version=%s, backend_ok=%s, root_ok=%s)",
    __version__, _BACKEND_OK, _ROOT_OK
)

# ===========================================================================
# SECTION 5: Helper guards (optional, for library users)
# ===========================================================================
def require_backend_modules(*modules: Iterable[str]) -> None:
    """
    اطمینان از موجود بودن ماژول‌های کلیدی بک‌اند. در صورت نبود، خطای واضح می‌دهد.
    مثال:
        require_backend_modules("config", "renderer")
    """
    missing: list[str] = []
    base = "videorobot.backend" if _BACKEND_OK else "videorobot"
    for m in modules or ("config", "renderer"):
        try:
            __import__(f"{base}.{m}")
        except Exception:
            missing.append(m)
    if missing:
        raise ImportError(
            "Missing required backend modules: "
            + ", ".join(missing)
            + f"\nChecked in base '{base}'. Make sure files exist and are importable."
        )

# ===========================================================================
# END OF FILE
# ===========================================================================
