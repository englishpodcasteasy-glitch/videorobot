# -*- coding: utf-8 -*-
"""
VideoRobot — Audio Processor (نسخه تمیز و کامل)

پردازش حرفه‌ای صوت با FFmpeg:
1. تبدیل به استریو 48kHz
2. اندازه‌گیری loudness هر کانال
3. اعمال gain مجزا به L/R
4. نرمال‌سازی دو مرحله‌ای EBU R128

مراجع:
- FFmpeg Filters: aformat, pan, channelsplit, volume, loudnorm
- EBU R128 loudness standard
- Two-pass loudnorm workflow
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, TypedDict

from .utils import sh

log = logging.getLogger("VideoRobot.audio")


# ===========================================================================
# SECTION 1: توابع کمکی
# ===========================================================================

# الگوی استخراج JSON از stderr
_JSON_PATTERN = re.compile(r"\{(?:[^{}]|(?R))*\}", re.DOTALL)


def _extract_last_json(stderr_text: str) -> Dict[str, Any]:
    """
    استخراج آخرین JSON block از خروجی stderr
    
    loudnorm فرمت JSON را در stderr چاپ می‌کند.
    این تابع آخرین JSON معتبر را برمی‌گرداند.
    
    Args:
        stderr_text: متن خروجی stderr
    
    Returns:
        دیکشنری JSON یا {} در صورت خطا
    """
    if not stderr_text:
        return {}
    
    try:
        last_match = None
        for match in _JSON_PATTERN.finditer(stderr_text):
            last_match = match.group(0)
        
        if not last_match:
            return {}
        
        return json.loads(last_match)
    except Exception as e:
        log.warning("خطا در parse کردن JSON loudnorm: %s", e)
        return {}


def _sanitize_db(value: float, min_val: float, max_val: float, default: float) -> float:
    """
    محدود کردن مقدار dB در محدوده امن
    
    Args:
        value: مقدار ورودی
        min_val: حداقل مجاز
        max_val: حداکثر مجاز
        default: مقدار پیش‌فرض در صورت نامعتبر بودن
    
    Returns:
        مقدار sanitize شده
    """
    try:
        if math.isnan(value) or math.isinf(value):
            return default
        return max(min_val, min(max_val, value))
    except (ValueError, TypeError):
        return default


def _coalesce(*values: Any, default: Any) -> Any:
    """
    برگرداندن اولین مقدار غیر None
    
    مشابه SQL COALESCE
    """
    for val in values:
        if val is not None:
            return val
    return default


def _ensure_directory(path: Path) -> None:
    """ایجاد دایرکتوری با مدیریت خطا"""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"خطا در ایجاد دایرکتوری: {path}") from e


def _get_binary_path(name: str, env_key: str, default: str) -> str:
    """دریافت مسیر باینری از env یا پیش‌فرض"""
    return os.getenv(env_key, default or name)


class _AudioInfo(TypedDict, total=False):
    """اطلاعات پایه استریم صوتی"""
    channels: int
    sample_rate: int
    layout: str


def _probe_audio_info(file_path: Path) -> _AudioInfo:
    """
    استخراج اطلاعات صوت با ffprobe
    
    Args:
        file_path: مسیر فایل صوتی
    
    Returns:
        دیکشنری حاوی channels, sample_rate, layout
    """
    ffprobe = _get_binary_path("ffprobe", "VR_FFPROBE_BIN", "ffprobe")
    
    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=channels,channel_layout,sample_rate",
        "-of", "json",
        str(file_path)
    ]
    
    result = sh(cmd, "ffprobe audio info", check=False)
    
    try:
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        
        return {
            "channels": int(stream.get("channels", 0) or 0),
            "sample_rate": int(stream.get("sample_rate", 0) or 0),
            "layout": str(stream.get("channel_layout") or ""),
        }
    except Exception as e:
        log.warning("خطا در parse کردن اطلاعات صوت: %s", e)
        return {"channels": 0, "sample_rate": 0, "layout": ""}


# ===========================================================================
# SECTION 2: مدل داده
# ===========================================================================

@dataclass(frozen=True)
class LoudnessTargets:
    """
    اهداف نرمال‌سازی EBU R128
    
    Attributes:
        I: Integrated Loudness (LUFS) - معمولاً -16.0
        LRA: Loudness Range (LU) - معمولاً 11.0
        TP: True Peak (dBFS) - معمولاً -2.0
    """
    I: float    # target LUFS
    LRA: float  # target loudness range
    TP: float   # target true peak


# ===========================================================================
# SECTION 3: کلاس اصلی AudioProcessor
# ===========================================================================

class AudioProcessor:
    """
    پردازشگر صوت با pipeline چند مرحله‌ای
    
    Pipeline:
    1. تبدیل به استریو 48kHz
    2. اندازه‌گیری loudness هر کانال
    3. اعمال gain مجزا به L/R
    4. نرمال‌سازی دو مرحله‌ای با loudnorm
    """
    
    def __init__(self, tmp: Path) -> None:
        """
        Args:
            tmp: مسیر دایرکتوری موقت برای فایل‌های میانی
        
        Raises:
            TypeError: اگر tmp از نوع Path نباشد
        """
        if not isinstance(tmp, Path):
            raise TypeError(f"tmp باید Path باشد، نه {type(tmp).__name__}")
        
        self.tmp = tmp
        _ensure_directory(self.tmp)
    
    # -----------------------------------------------------------------------
    # مرحله 1: تبدیل به استریو
    # -----------------------------------------------------------------------
    
    def _ensure_stereo(self, source: Path) -> Path:
        """
        اطمینان از استریو بودن با 48kHz
        
        رفتار:
        - مونو → تکثیر به استریو (L=R)
        - استریو → حفظ کانال‌های جداگانه
        - همیشه: 48kHz, PCM s16le
        
        Args:
            source: فایل ورودی
        
        Returns:
            مسیر فایل استریو شده
        
        Raises:
            FileNotFoundError: اگر فایل ورودی وجود نداشته باشد
        """
        if not isinstance(source, Path):
            raise TypeError(f"source باید Path باشد، نه {type(source).__name__}")
        
        if not source.exists():
            raise FileNotFoundError(f"فایل صوتی پیدا نشد: {source}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        output = self.tmp / "audio_stereo.wav"
        
        # تشخیص تعداد کانال‌ها
        info = _probe_audio_info(source)
        channels = info.get("channels", 0)
        
        # انتخاب فیلتر بر اساس تعداد کانال
        if channels == 1:
            # تکثیر مونو به استریو
            audio_filter = (
                "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,"
                "pan=stereo|c0=FL|c1=FL"
            )
        else:
            # حفظ استریو، فقط تبدیل فرمت
            audio_filter = "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo"
        
        sh(
            [
                ffmpeg, "-y", "-hide_banner", "-nostats",
                "-vn", "-sn",  # بدون ویدئو و زیرنویس
                "-i", str(source),
                "-af", audio_filter,
                "-c:a", "pcm_s16le",
                str(output)
            ],
            "تبدیل به استریو 48kHz"
        )
        
        log.debug("فایل به استریو تبدیل شد: %s", output)
        return output
    
    # -----------------------------------------------------------------------
    # مرحله 2: اندازه‌گیری loudness
    # -----------------------------------------------------------------------
    
    def _measure_loudness_per_channel(
        self,
        wav_file: Path,
        targets: LoudnessTargets
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        اندازه‌گیری مجزا loudness کانال‌های L و R
        
        از -map_channel برای جدا کردن کانال‌ها استفاده می‌شود.
        
        Args:
            wav_file: فایل استریو WAV
            targets: اهداف loudness
        
        Returns:
            (stats_left, stats_right): دو دیکشنری JSON loudnorm
        
        Raises:
            FileNotFoundError: اگر فایل وجود نداشته باشد
        """
        if not wav_file.exists():
            raise FileNotFoundError(f"فایل برای probe پیدا نشد: {wav_file}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        
        loudnorm_args = (
            f"loudnorm=I={targets.I}:LRA={targets.LRA}:TP={targets.TP}:"
            f"print_format=json"
        )
        
        # اندازه‌گیری کانال چپ (L)
        left_stderr = sh(
            [
                ffmpeg, "-hide_banner", "-nostats",
                "-i", str(wav_file),
                "-map_channel", "0.0.0",  # کانال اول
                "-af", loudnorm_args,
                "-f", "null", "-"
            ],
            "اندازه‌گیری loudness (L)",
            check=False
        ).stderr or ""
        
        # اندازه‌گیری کانال راست (R)
        right_stderr = sh(
            [
                ffmpeg, "-hide_banner", "-nostats",
                "-i", str(wav_file),
                "-map_channel", "0.0.1",  # کانال دوم
                "-af", loudnorm_args,
                "-f", "null", "-"
            ],
            "اندازه‌گیری loudness (R)",
            check=False
        ).stderr or ""
        
        left_stats = _extract_last_json(left_stderr)
        right_stats = _extract_last_json(right_stderr)
        
        return left_stats, right_stats
    
    # -----------------------------------------------------------------------
    # مرحله 3: اعمال gain
    # -----------------------------------------------------------------------
    
    def _apply_per_channel_gain(
        self,
        wav_file: Path,
        gain_left_db: float,
        gain_right_db: float
    ) -> Path:
        """
        اعمال gain مجزا به هر کانال
        
        استفاده از: channelsplit → volume → join
        
        Args:
            wav_file: فایل ورودی استریو
            gain_left_db: gain کانال چپ (dB)
            gain_right_db: gain کانال راست (dB)
        
        Returns:
            مسیر فایل با gain اعمال شده
        
        Raises:
            FileNotFoundError: اگر فایل وجود نداشته باشد
        """
        if not wav_file.exists():
            raise FileNotFoundError(f"فایل برای gain پیدا نشد: {wav_file}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        output = self.tmp / "audio_balanced.wav"
        
        # محدود کردن gain در محدوده امن
        gain_l = _sanitize_db(gain_left_db, -24.0, 24.0, 0.0)
        gain_r = _sanitize_db(gain_right_db, -24.0, 24.0, 0.0)
        
        # ساخت filter complex
        filter_complex = (
            "[0:a]channelsplit=channel_layout=stereo[FL][FR];"
            f"[FL]volume={gain_l:.3f}dB[FL2];"
            f"[FR]volume={gain_r:.3f}dB[FR2];"
            "[FL2][FR2]join=inputs=2:channel_layout=stereo[aout]"
        )
        
        sh(
            [
                ffmpeg, "-y", "-hide_banner", "-nostats",
                "-i", str(wav_file),
                "-filter_complex", filter_complex,
                "-map", "[aout]",
                "-ar", "48000",
                "-c:a", "pcm_s16le",
                str(output)
            ],
            "اعمال gain به کانال‌ها"
        )
        
        log.debug("Gain اعمال شد: L=%.2fdB, R=%.2fdB", gain_l, gain_r)
        return output
    
    # -----------------------------------------------------------------------
    # مرحله 4: نرمال‌سازی دو مرحله‌ای
    # -----------------------------------------------------------------------
    
    def _normalize_two_pass(
        self,
        wav_file: Path,
        targets: LoudnessTargets,
        *,
        codec: str,
        bitrate: str
    ) -> Path:
        """
        نرمال‌سازی دو مرحله‌ای با loudnorm
        
        مرحله 1: probe و استخراج آمار
        مرحله 2: اعمال با measured_* و offset
        
        Args:
            wav_file: فایل ورودی
            targets: اهداف loudness
            codec: کدک خروجی (مثلاً "aac")
            bitrate: bitrate (مثلاً "192k")
        
        Returns:
            مسیر فایل نرمال‌سازی شده
        
        Raises:
            FileNotFoundError: اگر فایل وجود نداشته باشد
            RuntimeError: اگر مرحله اول شکست بخورد
        """
        if not wav_file.exists():
            raise FileNotFoundError(f"فایل برای loudnorm پیدا نشد: {wav_file}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        
        # مرحله 1: probe
        probe_filter = (
            f"loudnorm=I={targets.I}:LRA={targets.LRA}:TP={targets.TP}:"
            f"print_format=json"
        )
        
        probe_stderr = sh(
            [
                ffmpeg, "-y", "-hide_banner", "-nostats",
                "-i", str(wav_file),
                "-af", probe_filter,
                "-f", "null", "-"
            ],
            "Loudnorm pass-1 (probe)",
            check=False
        ).stderr or ""
        
        stats = _extract_last_json(probe_stderr)
        if not stats:
            raise RuntimeError("مرحله اول loudnorm شکست خورد: JSON پیدا نشد")
        
        # استخراج آمار با fallback
        measured_I = float(_coalesce(
            stats.get("input_i"),
            stats.get("measured_I"),
            default=targets.I
        ))
        measured_LRA = float(_coalesce(
            stats.get("input_lra"),
            stats.get("measured_LRA"),
            default=11.0
        ))
        measured_TP = float(_coalesce(
            stats.get("input_tp"),
            stats.get("measured_TP"),
            default=-2.0
        ))
        measured_thresh = float(_coalesce(
            stats.get("input_thresh"),
            stats.get("measured_thresh"),
            default=-70.0
        ))
        offset = float(_coalesce(
            stats.get("target_offset"),
            stats.get("offset"),
            default=0.0
        ))
        
        # مرحله 2: اعمال
        output = self.tmp / "audio_loudnorm.m4a"
        
        apply_filter = (
            f"loudnorm=I={targets.I}:LRA={targets.LRA}:TP={targets.TP}:"
            f"measured_I={measured_I}:measured_LRA={measured_LRA}:"
            f"measured_TP={measured_TP}:measured_thresh={measured_thresh}:"
            f"offset={offset}:linear=true:print_format=summary"
        )
        
        # تنظیمات کدک
        encoder_args = ["-c:a", codec]
        if codec.lower() in {"aac", "libfdk_aac", "libopus", "libmp3lame"} and bitrate:
            encoder_args += ["-b:a", bitrate]
        
        sh(
            [
                ffmpeg, "-y", "-hide_banner", "-nostats",
                "-i", str(wav_file),
                "-af", apply_filter,
                "-ar", "48000",
                *encoder_args,
                str(output)
            ],
            "Loudnorm pass-2 (apply)"
        )
        
        log.debug(
            "Loudnorm تکمیل شد: measured(I/LRA/TP)=(%.2f/%.2f/%.2f), offset=%.2f",
            measured_I, measured_LRA, measured_TP, offset
        )
        
        return output
    
    # -----------------------------------------------------------------------
    # متد عمومی اصلی
    # -----------------------------------------------------------------------
    
    def normalize(self, source: Path, config: Any) -> Path:
        """
        Pipeline کامل نرمال‌سازی صوت
        
        مراحل:
        1. تبدیل به استریو 48kHz
        2. اندازه‌گیری loudness هر کانال
        3. اعمال gain پیش‌تنظیم به L/R
        4. نرمال‌سازی دو مرحله‌ای EBU R128
        
        Args:
            source: مسیر فایل صوتی ورودی
            config: شیء config با ویژگی‌های:
                - target_lufs: هدف LUFS (مثلاً -16.0)
                - target_lra: هدف LRA (مثلاً 11.0)
                - target_tp: هدف True Peak (مثلاً -2.0)
                - output_codec (اختیاری): کدک خروجی (پیش‌فرض: "aac")
                - output_bitrate (اختیاری): bitrate (پیش‌فرض: "192k")
        
        Returns:
            مسیر فایل صوتی نرمال‌سازی شده
        
        Raises:
            TypeError: اگر source یا config نامعتبر باشد
            FileNotFoundError: اگر فایل ورودی وجود نداشته باشد
        
        Example:
            >>> processor = AudioProcessor(Path("./tmp"))
            >>> normalized = processor.normalize(
            ...     Path("input.mp3"),
            ...     config
            ... )
        """
        if not isinstance(source, Path):
            raise TypeError(f"source باید Path باشد، نه {type(source).__name__}")
        
        if not source.exists():
            raise FileNotFoundError(f"فایل صوتی پیدا نشد: {source}")
        
        # استخراج اهداف از config
        try:
            targets = LoudnessTargets(
                I=float(config.target_lufs),
                LRA=float(config.target_lra),
                TP=float(config.target_tp),
            )
        except (AttributeError, ValueError, TypeError) as e:
            raise TypeError(
                "config باید دارای target_lufs, target_lra, target_tp باشد"
            ) from e
        
        # تنظیمات کدک
        codec = getattr(config, "output_codec", os.getenv("VR_AUDIO_CODEC", "aac"))
        bitrate = getattr(config, "output_bitrate", os.getenv("VR_AUDIO_BITRATE", "192k"))
        
        log.info("شروع نرمال‌سازی صوت: %s", source.name)
        
        # مرحله 1: استریو 48kHz
        stereo_file = self._ensure_stereo(source)
        
        # مرحله 2: اندازه‌گیری هر کانال
        left_stats, right_stats = self._measure_loudness_per_channel(stereo_file, targets)
        
        # استخراج loudness هر کانال
        input_left = float(_coalesce(
            left_stats.get("input_i"),
            left_stats.get("measured_I"),
            default=targets.I
        ))
        input_right = float(_coalesce(
            right_stats.get("input_i"),
            right_stats.get("measured_I"),
            default=targets.I
        ))
        
        # محاسبه gain لازم برای هر کانال
        gain_left = _sanitize_db(targets.I - input_left, -24.0, 24.0, 0.0)
        gain_right = _sanitize_db(targets.I - input_right, -24.0, 24.0, 0.0)
        
        # مرحله 3: اعمال gain
        balanced_file = self._apply_per_channel_gain(stereo_file, gain_left, gain_right)
        
        # مرحله 4: نرمال‌سازی نهایی
        final_file = self._normalize_two_pass(
            balanced_file,
            targets,
            codec=codec,
            bitrate=bitrate
        )
        
        log.info(
            "✅ نرمال‌سازی تکمیل شد: "
            "targets(I/LRA/TP)=(%.2f/%.2f/%.2f) | "
            "pre-gain(L/R)=(%.2f/%.2f)dB | "
            "codec=%s bitrate=%s",
            targets.I, targets.LRA, targets.TP,
            gain_left, gain_right,
            codec, bitrate
        )
        
        return final_file


# ===========================================================================
# پایان فایل
# ===========================================================================