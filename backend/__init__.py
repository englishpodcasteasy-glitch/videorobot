"""Backend package exposing VideoRobot services."""

from __future__ import annotations

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_ROOT.parent


def _read_version() -> str:
    version_file = _PROJECT_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


from .renderer import VideoComposer, Renderer  # noqa: E402  (import after path setup)

__all__ = ["__version__", "VideoComposer", "Renderer"]
__version__ = _read_version()
