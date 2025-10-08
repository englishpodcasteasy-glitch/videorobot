# -*- coding: utf-8 -*-
"""
VideoRobot — Package Initializer

مقداردهی اولیه پکیج:
- تعیین نسخه از metadata
- راه‌اندازی سیستم logging
- تعریف API عمومی
"""
from __future__ import annotations

import logging
import os
from importlib import metadata
from typing import Optional, TextIO

# ===========================================================================
# SECTION 1: تشخیص نسخه
# ===========================================================================

def _detect_version(package_name: str = "videorobot", fallback: str = "1.0.0") -> str:
    """
    خواندن نسخه پکیج از metadata
    
    در حالت‌های زیر fallback برمی‌گردد:
    - پکیج به صورت editable نصب شده
    - metadata در دسترس نیست
    - در حالت توسعه اجرا می‌شود
    
    Args:
        package_name: نام پکیج در PyPI
        fallback: نسخه پیش‌فرض
    
    Returns:
        رشته نسخه (مثلاً "1.2.3")
    """
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return fallback


__version__ = _detect_version()


# ===========================================================================
# SECTION 2: وارد کردن و صادر کردن کلاس‌های اصلی
# ===========================================================================

# وارد کردن کلاس‌های پیکربندی از ماژول config
from .config import (
    Paths,
    ProjectCfg,
    AudioCfg,
    CaptionCfg,
    FigureCfg,
    IntroOutroCfg,
    CTACfg,
    BGMCfg,
    BrollCfg,
    VisualCfg,
    ShortsCfg,
    Aspect,
    CaptionPosition,
    ShortsMode,
    FONTS,
)

# وارد کردن کلاس‌های اصلی از ماژول‌های دیگر
from .renderer import Renderer
from .scheduler import Scheduler
from .subtitles import SubtitleWriter
from .audio_processor import AudioProcessor

# وارد کردن توابع کمکی
from .utils import (
    sh,
    setup_logging,
    sanitize_filename,
    hex_to_0xRRGGBB,
    srt_time,
    hhmmss_cs,
    build_fonts_only,
    pick_default_font_name,
    mount_drive_once,
    resolve_drive_base,
    sync_from_drive_to_local,
    ensure_pkg_safe,
    docs_guard,
)


# ===========================================================================
# SECTION 3: تعریف API عمومی
# ===========================================================================

__all__ = [
    # کلاس‌های پیکربندی
    "Paths",
    "ProjectCfg",
    "AudioCfg",
    "CaptionCfg",
    "FigureCfg",
    "IntroOutroCfg",
    "CTACfg",
    "BGMCfg",
    "BrollCfg",
    "VisualCfg",
    "ShortsCfg",
    "Aspect",
    "CaptionPosition",
    "ShortsMode",
    "FONTS",
    
    # کلاس‌های اصلی
    "Renderer",
    "Scheduler",
    "SubtitleWriter",
    "AudioProcessor",
    
    # توابع کمکی
    "sh",
    "setup_logging",
    "sanitize_filename",
    "hex_to_0xRRGGBB",
    "srt_time",
    "hhmmss_cs",
    "build_fonts_only",
    "pick_default_font_name",
    "mount_drive_once",
    "resolve_drive_base",
    "sync_from_drive_to_local",
    "ensure_pkg_safe",
    "docs_guard",
    
    # متغیرها
    "__version__",
]


# ===========================================================================
# SECTION 4: سیستم Logging
# ===========================================================================

_LOGGER_NAME = "VideoRobot"
_DEFAULT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(
    *,
    level: Optional[int | str] = None,
    stream: Optional[TextIO] = None,
    fmt: Optional[str] = None,
) -> logging.Logger:
    """
    راه‌اندازی logger اصلی پروژه
    
    ویژگی‌ها:
    - Idempotent: چند بار فراخوانی مشکلی ایجاد نمی‌کند
    - قابل سفارشی‌سازی از طریق پارامتر یا env
    - پشتیبانی از غیرفعال‌سازی
    
    Args:
        level: سطح لاگ (int یا str مثل "INFO")
              None = خواندن از env یا پیش‌فرض INFO
        stream: جریان خروجی (None = stderr)
        fmt: فرمت لاگ (None = خواندن از env یا پیش‌فرض)
    
    Environment Variables:
        VIDEO_ROBOT_ENABLE_DEFAULT_LOGGING: "true"/"false" (پیش‌فرض: true)
        VIDEO_ROBOT_LOG_LEVEL: "DEBUG", "INFO", "WARNING", etc.
        VIDEO_ROBOT_LOG_FORMAT: فرمت دلخواه
    
    Returns:
        Logger پیکربندی شده
    
    Examples:
        >>> setup_logging(level="DEBUG")
        >>> setup_logging(level=logging.WARNING, fmt="%(message)s")
        >>> os.environ["VIDEO_ROBOT_LOG_LEVEL"] = "ERROR"
        >>> setup_logging()
    """
    logger = logging.getLogger(_LOGGER_NAME)
    
    # اگر قبلاً handler اضافه شده، دوباره‌کاری نکن
    if logger.handlers:
        return logger
    
    # بررسی فعال بودن logging از env
    enable_env = os.getenv("VIDEO_ROBOT_ENABLE_DEFAULT_LOGGING", "true")
    enable_default = enable_env.strip().lower() in {"1", "true", "yes", "on"}
    
    if not enable_default:
        # حالت کتابخانه‌ای: ساکت باش تا برنامه اصلی تنظیم کند
        logger.addHandler(logging.NullHandler())
        return logger
    
    # تعیین سطح لاگ
    if level is None:
        level = os.getenv("VIDEO_ROBOT_LOG_LEVEL", "INFO")
    
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    
    # تعیین فرمت
    log_format = fmt or os.getenv("VIDEO_ROBOT_LOG_FORMAT") or _DEFAULT_FORMAT
    
    # ساخت و پیکربندی handler
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(log_format))
    
    logger.addHandler(handler)
    logger.setLevel(level)
    
    return logger


# ===========================================================================
# SECTION 5: مقداردهی اولیه خودکار
# ===========================================================================

# راه‌اندازی logger پیش‌فرض
log = setup_logging()
log.debug("پکیج VideoRobot import شد (نسخه: %s)", __version__)


# ===========================================================================
# پایان فایل
# ===========================================================================

