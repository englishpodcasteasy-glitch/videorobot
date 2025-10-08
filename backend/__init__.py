# -*- coding: utf-8 -*-
"""
VideoRobot — backend package initializer (clean & robust)

- No nested "backend.backend" imports.
- Strictly relative imports inside the backend package.
- Optional compatibility shim for CaptionCfg.
- Logging bootstrap via utils.setup_logging with safe fallback.
"""

from __future__ import annotations

import logging
import os
from importlib import metadata
from typing import Iterable


# ---------------------------------------------------------------------------
# Version (best-effort; fine if it falls back when running from source)
# ---------------------------------------------------------------------------
def _detect_version(pkg: str = "videorobot", fallback: str = "0.0.0") -> str:
    try:
        return metadata.version(pkg)
    except Exception:
        return fallback


__version__ = _detect_version()


# ---------------------------------------------------------------------------
# Public surface (filled by imports below)
# ---------------------------------------------------------------------------
__all__ = [
    # Config layer
    "Paths", "ProjectCfg", "AudioCfg", "CaptionCfg", "FigureCfg",
    "IntroOutroCfg", "CTACfg", "BGMCfg", "BrollCfg", "VisualCfg",
    "ShortsCfg", "Aspect", "CaptionPosition", "ShortsMode", "FONTS",
    # Core classes
    "Renderer", "Scheduler", "SubtitleWriter", "AudioProcessor",
    # Utilities
    "sh", "setup_logging", "sanitize_filename", "hex_to_0xRRGGBB",
    "srt_time", "hhmmss_cs", "build_fonts_only", "pick_default_font_name",
    "mount_drive_once", "resolve_drive_base", "sync_from_drive_to_local",
    "ensure_pkg_safe", "docs_guard",
    # Vars/helpers
    "__version__", "make_caption_cfg_compat",
]


# ---------------------------------------------------------------------------
# Strict relative imports (this package lives at videorobot/backend/)
# ---------------------------------------------------------------------------
# Configs
from .config import (  # noqa: E402
    Paths, ProjectCfg, AudioCfg, CaptionCfg, FigureCfg, IntroOutroCfg,
    CTACfg, BGMCfg, BrollCfg, VisualCfg, ShortsCfg,
    Aspect, CaptionPosition, ShortsMode, FONTS,
)

# Core components
from .renderer import Renderer  # noqa: E402
from .scheduler import Scheduler  # noqa: E402
from .subtitles import SubtitleWriter  # noqa: E402
from .audio_processor import AudioProcessor  # noqa: E402

# Utilities
from .utils import (  # noqa: E402
    sh, setup_logging, sanitize_filename, hex_to_0xRRGGBB,
    srt_time, hhmmss_cs, build_fonts_only, pick_default_font_name,
    mount_drive_once, resolve_drive_base, sync_from_drive_to_local,
    ensure_pkg_safe, docs_guard,
)


# ---------------------------------------------------------------------------
# Logging bootstrap
# ---------------------------------------------------------------------------
def _bootstrap_logger() -> logging.Logger:
    try:
        level = os.getenv("VIDEO_ROBOT_LOG_LEVEL", "INFO")
        return setup_logging(level=level)
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        return logging.getLogger("VideoRobot")


log = _bootstrap_logger()
log.debug("videorobot.backend imported (version=%s)", __version__)


# ---------------------------------------------------------------------------
# Optional compatibility shim for CaptionCfg
# ---------------------------------------------------------------------------
def make_caption_cfg_compat(**kwargs) -> CaptionCfg:
    """
    Build a CaptionCfg while tolerating older/newer signatures.

    - Accepts either font_name or font_choice and maps appropriately.
    - Fills safe defaults for newer params when present.
    """
    import inspect

    sig = inspect.signature(CaptionCfg)
    allowed = set(sig.parameters.keys())

    # unify font args
    fname = kwargs.pop("font_name", None)
    fchoice = kwargs.pop("font_choice", None)
    font_val = fchoice or fname

    if "font_name" in allowed and "font_name" not in kwargs and font_val is not None:
        kwargs["font_name"] = font_val
    if "font_choice" in allowed and "font_choice" not in kwargs and font_val is not None:
        kwargs["font_choice"] = font_val

    # sensible defaults (only if present in the signature)
    defaults = dict(
        border_thickness=2,
        max_words_per_line=6,
        max_words_per_caption=32,
        margin_v=kwargs.get("margin_v", 70),
    )
    for k, v in defaults.items():
        if k in allowed and k not in kwargs:
            kwargs[k] = v

    # strip unknowns
    clean = {k: v for k, v in kwargs.items() if k in allowed}
    return CaptionCfg(**clean)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Guard utility for library users/tests
# ---------------------------------------------------------------------------
def require_backend_modules(*modules: Iterable[str]) -> None:
    """
    Ensure local backend modules exist and are importable.
    Example: require_backend_modules("config", "renderer")
    """
    miss = []
    base = __name__  # 'backend'
    for m in modules or ("config", "renderer"):
        try:
            __import__(f"{base}.{m}")
        except Exception:
            miss.append(m)
    if miss:
        raise ImportError(
            "Missing required backend modules: "
            + ", ".join(miss)
            + f"\nChecked in base '{base}'. Ensure files exist and import paths are relative (from .X import Y)."
        )
