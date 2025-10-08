# -*- coding: utf-8 -*-
"""
VideoRobot — Utilities (نسخه تمیز و کامل)

ابزارهای کمکی:
- اجرای امن subprocess
- مدیریت پکیج‌ها
- همگام‌سازی Google Drive
- مدیریت فونت‌ها
- پاکسازی نام فایل‌ها
- تبدیل رنگ و زمان
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Any, Dict

# ===========================================================================
# SECTION 0: Logging setup (اضافه شد تا ImportError حل شود)
# ===========================================================================

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

def setup_logging(level_env: str = "VR_LOG_LEVEL") -> logging.Logger:
    """
    Initialize consistent logging for VideoRobot.
    Reads level from env (default INFO) and returns the package logger.

    Safe to call multiple times in notebooks; handlers تکثیر نمی‌شوند.
    """
    level = os.getenv(level_env, "INFO").upper()
    lvl = getattr(logging, level, logging.INFO)

    root = logging.getLogger()
    # از تکثیر handlerها در Colab جلوگیری کنیم
    if not root.handlers:
        logging.basicConfig(level=lvl, format=LOG_FORMAT)
    else:
        root.setLevel(lvl)

    logger = logging.getLogger("VideoRobot")
    logger.setLevel(lvl)
    return logger

# ماژول را با یک logger پایدار بالا می‌آوریم
setup_logging()
log = logging.getLogger("VideoRobot.utils")

__all__ = [
    "setup_logging",
    "ShResult",
    "sh",
    "ensure_pkg_safe",
    "mount_drive_once",
    "resolve_drive_base",
    "sync_from_drive_to_local",
    "build_fonts_only",
    "pick_default_font_name",
    "sanitize_filename",
    "hex_to_0xRRGGBB",
    "srt_time",
    "hhmmss_cs",
    "docs_guard",
    "ensure_outputs_dir",
    "sha256_of_paths",
    "install_ffmpeg_if_needed",
]

# ===========================================================================
# SECTION 1: اجرای دستورات Shell
# ===========================================================================

@dataclass
class ShResult:
    """نتیجه اجرای یک دستور shell"""
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str


def _to_str_seq(cmd: Sequence[Any]) -> list[str]:
    """تبدیل ایمن آرگومان‌های command به رشته"""
    try:
        return [str(x) for x in cmd]
    except Exception:
        result = []
        for x in cmd:
            if isinstance(x, (bytes, bytearray)):
                result.append(x.decode("utf-8", "ignore"))
            else:
                result.append(str(x))
        return result


def sh(
    cmd: Sequence[str],
    desc: Optional[str] = None,
    *,
    check: bool = True,
    timeout: Optional[int] = None,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> ShResult:
    """
    اجرای امن subprocess با لاگ و مدیریت خطا

    Args:
        cmd: دستور به صورت لیست
        desc: توضیح برای لاگ
        check: اگر True باشد، خطا در صورت شکست
        timeout: محدودیت زمانی (ثانیه)
        cwd: مسیر اجرا
        env: متغیرهای محیطی

    Returns:
        ShResult با خروجی کامل

    Raises:
        ValueError: اگر دستور خالی باشد
        RuntimeError: اگر دستور fail شود (با check=True)
    """
    if not cmd:
        raise ValueError("دستور خالی است")

    str_cmd = _to_str_seq(cmd)

    if desc:
        log.info("→ %s", desc)

    try:
        proc = subprocess.run(
            str_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            env=env if env is not None else os.environ.copy(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"دستور timeout شد: {' '.join(str_cmd)}") from e

    result = ShResult(
        cmd=str_cmd,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or ""
    )

    if proc.returncode != 0 and check:
        msg = (
            f"دستور با خطا مواجه شد (code: {proc.returncode})\n"
            f"Command: {' '.join(str_cmd)}\n"
            f"STDERR: {result.stderr.strip()}"
        )
        raise RuntimeError(msg)

    return result


# ===========================================================================
# SECTION 2: مدیریت پکیج‌ها
# ===========================================================================

def ensure_pkg_safe(import_name: str, spec: str) -> None:
    """
    اطمینان از نصب پکیج Python

    اگر پکیج نصب نبود، با pip نصب می‌کند.

    Args:
        import_name: نام برای import (مثلاً 'PIL')
        spec: مشخصات pip (مثلاً 'Pillow==9.0.0')

    Example:
        ensure_pkg_safe('PIL', 'Pillow==9.0.0')
    """
    try:
        importlib.import_module(import_name)
        log.debug("پکیج %s از قبل نصب است", import_name)
        return
    except ImportError:
        pass

    log.info("در حال نصب پکیج: %s", spec)

    flags = [
        "--disable-pip-version-check",
        "--no-input",
        "--no-color",
        "--quiet",
    ]

    sh(
        [sys.executable, "-m", "pip", "install", *flags, spec],
        f"نصب {spec}",
        check=True
    )

    log.info("✅ پکیج %s نصب شد", spec)


# ===========================================================================
# SECTION 3: مدیریت Google Drive (Colab)
# ===========================================================================

def mount_drive_once() -> bool:
    """
    تلاش برای mount کردن Google Drive در Colab

    Returns:
        True اگر موفق بود یا قبلاً mount شده بود
    """
    try:
        from google.colab import drive  # type: ignore
        drive.mount("/content/drive", force_remount=False)
        log.info("✅ Google Drive mount شد")
        return True
    except ImportError:
        log.debug("google.colab موجود نیست (محیط غیر-Colab)")
        return False
    except Exception as e:
        log.info("Drive mount ناموفق بود: %s", e)
        return False


def resolve_drive_base() -> Optional[Path]:
    """
    پیدا کردن و ساخت ساختار پوشه VideoRobot در Drive

    Returns:
        Path به VideoRobot در Drive یا None اگر موجود نباشد
    """
    possible_roots = [
        Path("/content/drive/MyDrive"),
        Path("/content/drive/My Drive"),
    ]

    for root in possible_roots:
        try:
            if not root.exists():
                continue

            base = root / "VideoRobot"

            # ساخت ساختار پوشه‌ها
            subdirs = [
                "",
                "Assets",
                "Assets/Figures",
                "Assets/Music",
                "Broll",
                "Output",
            ]

            for subdir in subdirs:
                folder = base / subdir if subdir else base
                folder.mkdir(parents=True, exist_ok=True)

            log.info("✅ پوشه Drive پیدا شد: %s", base)
            return base

        except Exception as e:
            log.warning("خطا در ساخت پوشه‌های Drive: %s", e)

    log.info("Drive base پیدا نشد")
    return None


def _should_copy(src: Path, dst: Path) -> bool:
    """
    تصمیم‌گیری برای کپی فایل بر اساس اندازه و زمان

    Returns:
        True اگر файл باید کپی شود
    """
    if not dst.exists():
        return True

    try:
        src_stat = src.stat()
        dst_stat = dst.stat()

        # اگر اندازه فرق کند
        if src_stat.st_size != dst_stat.st_size:
            return True

        # اگر src جدیدتر باشد
        return src_stat.st_mtime > dst_stat.st_mtime

    except Exception:
        return True


def sync_from_drive_to_local(base_drive: Path, base_local: Path) -> None:
    """
    همگام‌سازی Assets و Broll از Drive به Local

    فقط فایل‌های تغییر یافته یا جدید کپی می‌شوند.

    Args:
        base_drive: مسیر پایه در Drive
        base_local: مسیر پایه در Local
    """
    log.info("شروع همگام‌سازی از Drive به Local...")

    for subdir in ("Assets", "Broll"):
        src = base_drive / subdir
        dst = base_local / subdir

        try:
            dst.mkdir(parents=True, exist_ok=True)

            if not src.exists():
                log.debug("پوشه منبع وجود ندارد: %s", src)
                continue

            copied_count = 0
            skipped_count = 0

            for item in src.rglob("*"):
                rel_path = item.relative_to(src)
                target = dst / rel_path

                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                if _should_copy(item, target):
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
                        copied_count += 1
                    except Exception as e:
                        log.warning("خطا در کپی: %s -> %s (%s)", item, target, e)
                else:
                    skipped_count += 1

            log.info(
                "✅ %s: %d فایل کپی شد, %d فایل رد شد",
                subdir, copied_count, skipped_count
            )

        except Exception as e:
            log.warning("خطا در همگام‌سازی '%s': %s", subdir, e)


# ===========================================================================
# SECTION 4: مدیریت فونت‌ها
# ===========================================================================

_FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}


def build_fonts_only(font_root: Path, tmp: Path) -> Path:
    """
    کپی فقط فایل‌های فونت برای استفاده در ffmpeg

    در صورت برخورد نام، suffix عددی اضافه می‌شود.

    Args:
        font_root: مسیر ریشه فونت‌ها
        tmp: مسیر موقت

    Returns:
        Path به پوشه فونت‌های کپی شده
    """
    output_dir = tmp / "fonts_ffmpeg"
    output_dir.mkdir(parents=True, exist_ok=True)

    name_counter: Dict[str, int] = {}
    copied_count = 0

    for font_file in Path(font_root).rglob("*"):
        if not font_file.is_file():
            continue

        if font_file.suffix.lower() not in _FONT_EXTENSIONS:
            continue

        target_name = font_file.name

        # مدیریت برخورد نام
        if (output_dir / target_name).exists() or target_name in name_counter:
            name_counter[target_name] = name_counter.get(target_name, 0) + 1
            stem = font_file.stem
            suffix = font_file.suffix
            target_name = f"{stem}_{name_counter[target_name]}{suffix}"

        try:
            shutil.copy2(font_file, output_dir / target_name)
            copied_count += 1
        except Exception as e:
            log.warning("خطا در کپی فونت: %s -> %s (%s)", font_file, target_name, e)

    log.info("✅ %d فونت کپی شد به: %s", copied_count, output_dir)
    return output_dir


def pick_default_font_name(font_root: Path) -> str:
    """
    انتخاب نام فونت پیش‌فرض از اولین فایل فونت

    Args:
        font_root: مسیر ریشه فونت‌ها

    Returns:
        نام فونت (بدون پسوند) یا "DejaVu Sans" به عنوان fallback
    """
    try:
        for item in Path(font_root).iterdir():
            if item.is_file() and item.suffix.lower() in _FONT_EXTENSIONS:
                return item.stem
    except Exception as e:
        log.debug("خطا در یافتن فونت پیش‌فرض: %s", e)

    return "DejaVu Sans"


# ===========================================================================
# SECTION 5: پاکسازی نام فایل
# ===========================================================================

_SAFE_CHARS_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str, *, max_len: int = 120) -> str:
    """
    پاکسازی نام فایل برای ایمنی در سیستم فایل

    - نرمال‌سازی Unicode
    - تبدیل فاصله به _
    - حذف کاراکترهای غیرمجاز
    - محدودیت طول
    - حفظ پسوند فایل

    Args:
        name: نام اصلی فایل
        max_len: حداکثر طول مجاز

    Returns:
        نام پاک‌شده

    Examples:
        sanitize_filename("مثال تست.mp4") -> "output.mp4"
        sanitize_filename("my video!@#.mp4") -> "my_video.mp4"
    """
    # نرمال‌سازی Unicode
    normalized = unicodedata.normalize("NFKC", str(name or "").strip())

    # تبدیل فاصله به زیرخط
    normalized = normalized.replace(" ", "_")

    # جدا کردن پسوند
    if "." in normalized:
        stem, dot, ext = normalized.rpartition(".")
    else:
        stem, dot, ext = normalized, "", ""

    # حذف کاراکترهای غیرمجاز
    stem = _SAFE_CHARS_PATTERN.sub("", stem)

    # fallback اگر خالی شد
    if not stem:
        stem = "output"

    # محدود کردن طول (با حفظ جای پسوند)
    max_stem_len = max(1, max_len - len(dot) - len(ext))
    if len(stem) > max_stem_len:
        stem = stem[:max_stem_len]

    return f"{stem}{dot}{ext}" if ext else stem


# ===========================================================================
# SECTION 6: تبدیل رنگ
# ===========================================================================

def hex_to_0xRRGGBB(hex_color: str) -> str:
    """
    تبدیل رنگ hex به فرمت 0xRRGGBB برای ffmpeg

    فرمت‌های پشتیبانی شده:
    - "#RRGGBB" -> "0xRRGGBB"
    - "RRGGBB" -> "0xRRGGBB"
    - "#RGB" -> "0xRRGGBB" (هر رقم دوبار تکرار می‌شود)
    - "RGB" -> "0xRRGGBB"

    Args:
        hex_color: رنگ به فرمت hex

    Returns:
        رنگ به فرمت 0xRRGGBB یا "0xFFFFFF" در صورت خطا

    Examples:
        hex_to_0xRRGGBB("#FF5733") -> "0xFF5733"
        hex_to_0xRRGGBB("00FF00") -> "0x00FF00"
        hex_to_0xRRGGBB("#F00") -> "0xFF0000"
        hex_to_0xRRGGBB("invalid") -> "0xFFFFFF"
    """
    h = str(hex_color or "").strip()

    # حذف # اگر وجود داشت
    if h.startswith("#"):
        h = h[1:]

    # تبدیل فرمت کوتاه RGB به RRGGBB
    if re.fullmatch(r"[0-9A-Fa-f]{3}", h):
        h = "".join(char * 2 for char in h)

    # اعتبارسنجی فرمت نهایی
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        log.warning("رنگ نامعتبر '%s', استفاده از سفید", hex_color)
        return "0xFFFFFF"

    return "0x" + h.upper()


# ===========================================================================
# SECTION 7: فرمت‌دهی زمان
# ===========================================================================

def srt_time(seconds: float) -> str:
    """
    تبدیل ثانیه به فرمت زمان SRT

    Format: HH:MM:SS,mmm

    Args:
        seconds: زمان به ثانیه

    Returns:
        رشته فرمت شده

    Example:
        srt_time(65.5) -> "00:01:05,500"
    """
    ms = int(round(max(0.0, float(seconds)) * 1000))

    hours, remainder = divmod(ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1_000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def hhmmss_cs(seconds: float) -> str:
    """
    تبدیل ثانیه به فرمت زمان ASS

    Format: H:MM:SS.cc (centiseconds)

    Args:
        seconds: زمان به ثانیه

    Returns:
        رشته فرمت شده

    Example:
        hhmmss_cs(65.5) -> "0:01:05.50"
    """
    centiseconds = int(round(max(0.0, float(seconds)) * 100))

    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, cs = divmod(remainder, 100)

    return f"{hours:01d}:{minutes:02d}:{secs:02d}.{cs:02d}"


# ===========================================================================
# SECTION 8: مدیریت دایرکتوری‌ها
# ===========================================================================

def docs_guard() -> None:
    """
    ایجاد دایرکتوری‌های اصلی پروژه

    از متغیرهای محیطی زیر پشتیبانی می‌کند:
    - VR_BASE_LOCAL: مسیر پایه (پیش‌فرض: /content/VideoRobot)
    - VR_TMP_DIR: مسیر موقت (پیش‌فرض: BASE/_vr_tmp)
    - VR_OUT_DIR: مسیر خروجی (پیش‌فرض: BASE/_vr_out)
    - VR_ASSETS_DIR: مسیر Assets (پیش‌فرض: BASE/Assets)
    """
    base = Path(os.getenv("VR_BASE_LOCAL", "/content/VideoRobot"))
    tmp = Path(os.getenv("VR_TMP_DIR", str(base / "_vr_tmp")))
    output = Path(os.getenv("VR_OUT_DIR", str(base / "_vr_out")))
    assets = Path(os.getenv("VR_ASSETS_DIR", str(base / "Assets")))

    directories = {
        "base": base,
        "tmp": tmp,
        "output": output,
        "assets": assets,
    }

    for name, path in directories.items():
        try:
            path.mkdir(parents=True, exist_ok=True)
            log.debug("✅ دایرکتوری %s ایجاد شد: %s", name, path)
        except Exception as e:
            log.warning("خطا در ایجاد دایرکتوری %s (%s): %s", name, path, e)

    log.info("✅ همه دایرکتوری‌ها آماده هستند")


# ===========================================================================
# SECTION 9: Render helpers
# ===========================================================================


def ensure_outputs_dir() -> Path:
    """Return the best writable outputs directory (Colab-first)."""

    candidates = [Path("/content/outputs"), Path("./outputs")]

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            log.debug("Using outputs directory: %s", candidate)
            return candidate
        except Exception as exc:  # pragma: no cover - filesystem guards
            log.debug("Output dir %s not writable: %s", candidate, exc)

    fallback = Path("./outputs")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def sha256_of_paths(paths: Sequence[Path]) -> str:
    """Compute a deterministic SHA256 digest from file stats."""

    sha = hashlib.sha256()
    resolved: list[Path] = []

    for path in paths:
        candidate = Path(path)
        resolved.append(candidate.resolve())

    for path in sorted(resolved):
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Asset not found: {path}")

        stat = path.stat()
        payload = f"{path}|{stat.st_size}|{int(stat.st_mtime_ns)}"
        sha.update(payload.encode("utf-8"))

    return sha.hexdigest()


def install_ffmpeg_if_needed() -> None:
    """Ensure ffmpeg is available, raising a clear error otherwise."""

    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - runtime guard
        raise RuntimeError(
            "ffmpeg binary not found. Run scripts/install_ffmpeg_colab.sh in Colab."
        ) from exc
    except subprocess.CalledProcessError as exc:  # pragma: no cover - runtime guard
        raise RuntimeError(f"ffmpeg is not healthy: {exc.stderr}") from exc


# ===========================================================================
# پایان فایل
# ===========================================================================