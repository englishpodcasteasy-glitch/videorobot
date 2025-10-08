# -*- coding: utf-8 -*-
"""
VideoRobot — Audio Processor (Clean & Complete Version)

Professional audio processing with FFmpeg:
1. Converts to stereo 48kHz
2. Measures loudness per channel
3. Applies per-channel gain
4. Performs two-pass EBU R128 normalization

References:
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
from .config import Something  # یا: from . import config

from .utils import sh

log = logging.getLogger("VideoRobot.audio")


# ===========================================================================
# SECTION 1: Helper Functions
# ===========================================================================

# Pattern to extract JSON from stderr.
# This non-recursive pattern is compatible with Python's re module and finds JSON objects, including nested ones.
_JSON_PATTERN = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _extract_last_json(stderr_text: str) -> Dict[str, Any]:
    """
    Extracts the last JSON block from stderr output.

    The loudnorm filter prints its stats in JSON format to stderr.
    This function finds and parses the last valid JSON block.

    Args:
        stderr_text: The text from stderr.

    Returns:
        A dictionary parsed from the JSON, or an empty dict on error.
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
        log.warning("Error parsing loudnorm JSON: %s", e)
        return {}


def _sanitize_db(value: float, min_val: float, max_val: float, default: float) -> float:
    """
    Clamps a decibel value within a safe range.

    Args:
        value: The input value.
        min_val: The minimum allowed value.
        max_val: The maximum allowed value.
        default: The default value if the input is invalid.

    Returns:
        The sanitized value.
    """
    try:
        if math.isnan(value) or math.isinf(value):
            return default
        return max(min_val, min(max_val, value))
    except (ValueError, TypeError):
        return default


def _coalesce(*values: Any, default: Any) -> Any:
    """
    Returns the first non-None value.
    Similar to SQL COALESCE.
    """
    for val in values:
        if val is not None:
            return val
    return default


def _ensure_directory(path: Path) -> None:
    """Creates a directory with error handling."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"Error creating directory: {path}") from e


def _get_binary_path(name: str, env_key: str, default: str) -> str:
    """Gets a binary path from an environment variable or a default."""
    return os.getenv(env_key, default or name)


class _AudioInfo(TypedDict, total=False):
    """Basic audio stream information."""
    channels: int
    sample_rate: int
    layout: str


def _probe_audio_info(file_path: Path) -> _AudioInfo:
    """
    Extracts audio information using ffprobe.

    Args:
        file_path: The path to the audio file.

    Returns:
        A dictionary containing channels, sample_rate, and layout.
    """
    ffprobe = _get_binary_path("ffprobe", "VR_FFPROBE_BIN", "ffprobe")
    
    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=channels,channel_layout,sample_rate",
        "-of", "json",
        str(file_path)
    ]
    
    result = sh(cmd, "Probe audio info", check=False)
    
    try:
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        
        return {
            "channels": int(stream.get("channels", 0) or 0),
            "sample_rate": int(stream.get("sample_rate", 0) or 0),
            "layout": str(stream.get("channel_layout") or ""),
        }
    except Exception as e:
        log.warning("Error parsing audio info: %s", e)
        return {"channels": 0, "sample_rate": 0, "layout": ""}


# ===========================================================================
# SECTION 2: Data Models
# ===========================================================================

@dataclass(frozen=True)
class LoudnessTargets:
    """
    EBU R128 normalization targets.

    Attributes:
        I: Integrated Loudness (LUFS) - typically -16.0
        LRA: Loudness Range (LU) - typically 11.0
        TP: True Peak (dBFS) - typically -2.0
    """
    I: float    # target LUFS
    LRA: float  # target loudness range
    TP: float   # target true peak


# ===========================================================================
# SECTION 3: Main AudioProcessor Class
# ===========================================================================

class AudioProcessor:
    """
    Processes audio with a multi-stage pipeline.

    Pipeline:
    1. Convert to stereo 48kHz
    2. Measure loudness per channel
    3. Apply per-channel gain
    4. Two-pass normalization with loudnorm
    """
    
    def __init__(self, tmp: Path) -> None:
        """
        Args:
            tmp: The path to the temporary directory for intermediate files.
        
        Raises:
            TypeError: If tmp is not a Path object.
        """
        if not isinstance(tmp, Path):
            raise TypeError(f"tmp must be a Path, not {type(tmp).__name__}")
        
        self.tmp = tmp
        _ensure_directory(self.tmp)
    
    # -----------------------------------------------------------------------
    # Stage 1: Ensure Stereo
    # -----------------------------------------------------------------------
    
    def _ensure_stereo(self, source: Path) -> Path:
        """
        Ensures the audio is stereo at 48kHz.

        Behavior:
        - Mono → Duplicates to stereo (L=R)
        - Stereo → Preserves separate channels
        - Always: 48kHz, PCM s16le
        
        Args:
            source: The input file.
        
        Returns:
            The path to the stereo-converted file.
        
        Raises:
            FileNotFoundError: If the input file does not exist.
        """
        if not isinstance(source, Path):
            raise TypeError(f"source must be a Path, not {type(source).__name__}")
        
        if not source.exists():
            raise FileNotFoundError(f"Audio file not found: {source}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        output = self.tmp / "audio_stereo.wav"
        
        # Detect number of channels
        info = _probe_audio_info(source)
        channels = info.get("channels", 0)
        
        # Choose filter based on channel count
        if channels == 1:
            # Duplicate mono to stereo
            audio_filter = (
                "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,"
                "pan=stereo|c0=FL|c1=FL"
            )
        else:
            # Preserve stereo, just convert format
            audio_filter = "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo"
        
        sh(
            [
                ffmpeg, "-y", "-hide_banner", "-nostats",
                "-vn", "-sn",  # No video, no subtitles
                "-i", str(source),
                "-af", audio_filter,
                "-c:a", "pcm_s16le",
                str(output)
            ],
            "Convert to stereo 48kHz"
        )
        
        log.debug("File converted to stereo: %s", output)
        return output
    
    # -----------------------------------------------------------------------
    # Stage 2: Measure Loudness
    # -----------------------------------------------------------------------
    
    def _measure_loudness_per_channel(
        self,
        wav_file: Path,
        targets: LoudnessTargets
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Measures loudness for L and R channels separately.

        Uses -map_channel to isolate channels.
        
        Args:
            wav_file: The stereo WAV file.
            targets: The loudness targets.
        
        Returns:
            (stats_left, stats_right): Two loudnorm JSON dictionaries.
        
        Raises:
            FileNotFoundError: If the file does not exist.
        """
        if not wav_file.exists():
            raise FileNotFoundError(f"File for probe not found: {wav_file}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        
        loudnorm_args = (
            f"loudnorm=I={targets.I}:LRA={targets.LRA}:TP={targets.TP}:"
            f"print_format=json"
        )
        
        # Measure left channel (L)
        left_stderr = sh(
            [
                ffmpeg, "-hide_banner", "-nostats",
                "-i", str(wav_file),
                "-map_channel", "0.0.0",  # First channel
                "-af", loudnorm_args,
                "-f", "null", "-"
            ],
            "Measure loudness (L)",
            check=False
        ).stderr or ""
        
        # Measure right channel (R)
        right_stderr = sh(
            [
                ffmpeg, "-hide_banner", "-nostats",
                "-i", str(wav_file),
                "-map_channel", "0.0.1",  # Second channel
                "-af", loudnorm_args,
                "-f", "null", "-"
            ],
            "Measure loudness (R)",
            check=False
        ).stderr or ""
        
        left_stats = _extract_last_json(left_stderr)
        right_stats = _extract_last_json(right_stderr)
        
        return left_stats, right_stats
    
    # -----------------------------------------------------------------------
    # Stage 3: Apply Gain
    # -----------------------------------------------------------------------
    
    def _apply_per_channel_gain(
        self,
        wav_file: Path,
        gain_left_db: float,
        gain_right_db: float
    ) -> Path:
        """
        Applies separate gain to each channel.

        Uses: channelsplit → volume → join
        
        Args:
            wav_file: The input stereo file.
            gain_left_db: Gain for the left channel (dB).
            gain_right_db: Gain for the right channel (dB).
        
        Returns:
            The path to the gain-adjusted file.
        
        Raises:
            FileNotFoundError: If the file does not exist.
        """
        if not wav_file.exists():
            raise FileNotFoundError(f"File for gain not found: {wav_file}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        output = self.tmp / "audio_balanced.wav"
        
        # Clamp gain to a safe range
        gain_l = _sanitize_db(gain_left_db, -24.0, 24.0, 0.0)
        gain_r = _sanitize_db(gain_right_db, -24.0, 24.0, 0.0)
        
        # Build filter complex
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
            "Apply gain to channels"
        )
        
        log.debug("Gain applied: L=%.2fdB, R=%.2fdB", gain_l, gain_r)
        return output
    
    # -----------------------------------------------------------------------
    # Stage 4: Two-Pass Normalization
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
        Performs two-pass normalization with loudnorm.

        Pass 1: Probes and extracts statistics.
        Pass 2: Applies normalization using measured_* and offset.
        
        Args:
            wav_file: The input file.
            targets: The loudness targets.
            codec: The output codec (e.g., "aac").
            bitrate: The output bitrate (e.g., "192k").
        
        Returns:
            The path to the normalized file.
        
        Raises:
            FileNotFoundError: If the file does not exist.
            RuntimeError: If the first pass fails.
        """
        if not wav_file.exists():
            raise FileNotFoundError(f"File for loudnorm not found: {wav_file}")
        
        ffmpeg = _get_binary_path("ffmpeg", "VR_FFMPEG_BIN", "ffmpeg")
        
        # Pass 1: Probe
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
            raise RuntimeError("Loudnorm pass-1 failed: JSON not found")
        
        # Extract stats with fallbacks
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
        
        # Pass 2: Apply
        output = self.tmp / "audio_loudnorm.m4a"
        
        apply_filter = (
            f"loudnorm=I={targets.I}:LRA={targets.LRA}:TP={targets.TP}:"
            f"measured_I={measured_I}:measured_LRA={measured_LRA}:"
            f"measured_TP={measured_TP}:measured_thresh={measured_thresh}:"
            f"offset={offset}:linear=true:print_format=summary"
        )
        
        # Codec settings
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
            "Loudnorm complete: measured(I/LRA/TP)=(%.2f/%.2f/%.2f), offset=%.2f",
            measured_I, measured_LRA, measured_TP, offset
        )
        
        return output
    
    # -----------------------------------------------------------------------
    # Main Public Method
    # -----------------------------------------------------------------------
    
    def normalize(self, source: Path, config: Any) -> Path:
        """
        Full audio normalization pipeline.
        
        Stages:
        1. Convert to stereo 48kHz
        2. Measure loudness per channel
        3. Apply pre-gain to L/R
        4. Two-pass EBU R128 normalization
        
        Args:
            source: Path to the input audio file.
            config: A config object with attributes:
                - target_lufs: Target LUFS (e.g., -16.0)
                - target_lra: Target LRA (e.g., 11.0)
                - target_tp: Target True Peak (e.g., -2.0)
                - output_codec (optional): Output codec (default: "aac")
                - output_bitrate (optional): Output bitrate (default: "192k")
        
        Returns:
            Path to the normalized audio file.
        
        Raises:
            TypeError: If source or config is invalid.
            FileNotFoundError: If the input file does not exist.
        
        Example:
            >>> processor = AudioProcessor(Path("./tmp"))
            >>> normalized = processor.normalize(
            ...     Path("input.mp3"),
            ...     config
            ... )
        """
        if not isinstance(source, Path):
            raise TypeError(f"source must be a Path, not {type(source).__name__}")
        
        if not source.exists():
            raise FileNotFoundError(f"Audio file not found: {source}")
        
        # Extract targets from config
        try:
            targets = LoudnessTargets(
                I=float(config.target_lufs),
                LRA=float(config.target_lra),
                TP=float(config.target_tp),
            )
        except (AttributeError, ValueError, TypeError) as e:
            raise TypeError(
                "config must have target_lufs, target_lra, and target_tp attributes"
            ) from e
        
        # Codec settings
        codec = getattr(config, "output_codec", os.getenv("VR_AUDIO_CODEC", "aac"))
        bitrate = getattr(config, "output_bitrate", os.getenv("VR_AUDIO_BITRATE", "192k"))
        
        log.info("Starting audio normalization: %s", source.name)
        
        # Stage 1: Stereo 48kHz
        stereo_file = self._ensure_stereo(source)
        
        # Stage 2: Measure each channel
        left_stats, right_stats = self._measure_loudness_per_channel(stereo_file, targets)
        
        # Extract loudness of each channel
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
        
        # Calculate necessary gain for each channel
        gain_left = _sanitize_db(targets.I - input_left, -24.0, 24.0, 0.0)
        gain_right = _sanitize_db(targets.I - input_right, -24.0, 24.0, 0.0)
        
        # Stage 3: Apply gain
        balanced_file = self._apply_per_channel_gain(stereo_file, gain_left, gain_right)
        
        # Stage 4: Final normalization
        final_file = self._normalize_two_pass(
            balanced_file,
            targets,
            codec=codec,
            bitrate=bitrate
        )
        
        log.info(
            "✅ Normalization complete: "
            "targets(I/LRA/TP)=(%.2f/%.2f/%.2f) | "
            "pre-gain(L/R)=(%.2f/%.2f)dB | "
            "codec=%s bitrate=%s",
            targets.I, targets.LRA, targets.TP,
            gain_left, gain_right,
            codec, bitrate
        )
        
        return final_file


# ===========================================================================
# End of File

# ===========================================================================


