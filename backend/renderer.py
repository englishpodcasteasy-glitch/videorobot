"""Deterministic MoviePy-based video composer for the renderer service."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --- MoviePy 1.x / 2.x compatibility layer (fix for missing `moviepy.editor`) ---
try:
    # MoviePy >= 2.0 (no `editor` module)
    from moviepy import (
        AudioFileClip,
        VideoFileClip,
        ImageClip,
        ColorClip,
        CompositeVideoClip,
        concatenate_videoclips,
    )
    from moviepy.audio import fx as afx
    from moviepy.video import fx as vfx
    try:
        from moviepy.audio.compositing import CompositeAudioClip
    except Exception:
        # some builds keep it under AudioClip
        from moviepy.audio.AudioClip import CompositeAudioClip  # type: ignore

    class _MPEShim:
        AudioFileClip = AudioFileClip
        VideoFileClip = VideoFileClip
        ImageClip = ImageClip
        ColorClip = ColorClip
        CompositeVideoClip = CompositeVideoClip
        CompositeAudioClip = CompositeAudioClip
        concatenate_videoclips = staticmethod(concatenate_videoclips)

    mpe = _MPEShim()  # type: ignore

except Exception:
    # MoviePy 1.x fallback (has `editor`)
    import moviepy.editor as mpe  # type: ignore
    from moviepy.audio.fx import all as afx  # type: ignore
    from moviepy.video.fx import all as vfx  # type: ignore

    # normalize names (used by type hints below)
    AudioFileClip = mpe.AudioFileClip
    VideoFileClip = mpe.VideoFileClip
    ImageClip = mpe.ImageClip
    ColorClip = mpe.ColorClip
    CompositeVideoClip = mpe.CompositeVideoClip
    try:
        CompositeAudioClip = mpe.CompositeAudioClip
    except Exception:
        from moviepy.audio.compositing import CompositeAudioClip  # type: ignore
# ------------------------------------------------------------------------------

from .utils import sha256_of_paths


class VideoComposer:
    """Compose MP4 videos deterministically from a manifest definition."""

    def __init__(self) -> None:
        self._log = logging.getLogger("VideoRobot.VideoComposer")
        self._last_duration_ms: Optional[int] = None
        self._last_inputs_sha256: Optional[str] = None
        self._manifest_path: Optional[Path] = None
        self._work_dir: Optional[Path] = None

    def compose(self, manifest: Dict[str, Any], work_dir: Path) -> Path:
        """Compose the final MP4 file described by ``manifest`` into ``work_dir``."""

        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a dict")

        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir = work_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        seed = manifest.get("seed")
        if seed is not None:
            try:
                seed_int = int(seed)
            except (TypeError, ValueError) as exc:  # pragma: no cover - validation guard
                raise ValueError("seed must be an integer") from exc
            random.seed(seed_int)
            np.random.seed(seed_int)
        else:
            random.seed()
            np.random.seed()

        video_cfg = manifest.get("video") or {}
        width = int(video_cfg.get("width", 1280) or 1280)
        height = int(video_cfg.get("height", 720) or 720)
        fps = float(video_cfg.get("fps", 30) or 30)
        if width <= 0 or height <= 0:
            raise ValueError("video dimensions must be positive")
        if fps <= 0:
            raise ValueError("fps must be positive")

        bg_color = self._parse_color(video_cfg.get("bg_color"), default=(16, 19, 24))

        _, tracks, _ = self.prepare_manifest(manifest, work_dir)

        visual_layers: List[mpe.VideoClip] = []
        audio_specs: List[Dict[str, Any]] = []
        resources: List[Any] = []
        resource_ids: set[int] = set()
        total_duration = 0.0
        last_video_index: Optional[int] = None

        def remember(clip: Any) -> Any:
            if hasattr(clip, "close"):
                ident = id(clip)
                if ident not in resource_ids:
                    resources.append(clip)
                    resource_ids.add(ident)
            return clip

        try:
            for track in tracks:
                ttype = (track.get("type") or "").lower()
                if ttype == "audio":
                    audio_specs.append(track)
                    continue

                if ttype == "video":
                    clip, clip_duration = self._build_video_clip(track, width, height, remember)
                    crossfade = float(track.get("crossfade", 0.5) or 0.0)
                    if crossfade > 0 and last_video_index is not None:
                        prev = visual_layers[last_video_index]
                        prev_faded = remember(vfx.fadeout(prev, crossfade))
                        visual_layers[last_video_index] = prev_faded
                        clip = remember(vfx.fadein(clip, crossfade))
                    last_video_index = len(visual_layers)
                elif ttype == "image":
                    clip, clip_duration = self._build_image_clip(track, remember)
                elif ttype == "text":
                    clip, clip_duration = self._build_text_clip(track, remember)
                else:
                    raise ValueError(f"Unsupported track type: {ttype}")

                start = float(track.get("start", 0.0) or 0.0)
                clip = remember(clip.set_start(start))
                visual_layers.append(clip)
                total_duration = max(total_duration, start + clip_duration)

            if total_duration <= 0:
                total_duration = 1.0

            audio_layers: List[mpe.AudioClip] = []
            for track in audio_specs:
                clip, clip_duration = self._build_audio_clip(track, total_duration, remember)
                start = float(track.get("start", 0.0) or 0.0)
                clip = remember(clip.set_start(start))
                audio_layers.append(clip)
                total_duration = max(total_duration, start + clip_duration)

            base_clip = remember(
                mpe.ColorClip(size=(width, height), color=bg_color).set_duration(total_duration)
            )
            visual_layers.insert(0, base_clip)

            final_clip = remember(
                mpe.CompositeVideoClip(visual_layers, size=(width, height)).set_duration(total_duration)
            )

            if audio_layers:
                audio_mix = remember(CompositeAudioClip(audio_layers))
                final_clip = remember(final_clip.set_audio(audio_mix))

            output_path = work_dir / "final.mp4"
            temp_audio = chunks_dir / "temp-audio.m4a"
            final_clip.write_videofile(
                str(output_path),
                fps=fps,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=str(temp_audio),
                remove_temp=True,
                threads=4,
                logger=None,
            )

            duration_ms = int(math.ceil(final_clip.duration * 1000))
            self._last_duration_ms = duration_ms
            return output_path
        finally:
            for clip in reversed(resources):
                try:
                    clip.close()
                except Exception:  # pragma: no cover - resource cleanup guard
                    continue

    @property
    def last_duration_ms(self) -> Optional[int]:
        return self._last_duration_ms

    @property
    def last_inputs_sha256(self) -> Optional[str]:
        return self._last_inputs_sha256

    @property
    def manifest_path(self) -> Optional[Path]:
        return self._manifest_path

    def prepare_manifest(
        self, manifest: Dict[str, Any], work_dir: Path
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
        """Normalise manifest, resolve assets, and compute the inputs hash."""

        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a dict")

        self._work_dir = Path(work_dir)
        tracks = manifest.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            raise ValueError("tracks must be a non-empty list")

        canonical_manifest = self._canonicalize(manifest)
        manifest_path = self._work_dir / "manifest_canonical.json"
        manifest_path.write_text(
            json.dumps(canonical_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._manifest_path = manifest_path

        asset_paths = self._collect_asset_paths(tracks)
        inputs_hash = self._write_inputs_hash(self._work_dir, canonical_manifest, asset_paths)
        self._last_inputs_sha256 = inputs_hash
        return canonical_manifest, tracks, inputs_hash

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_video_clip(
        self,
        track: Dict[str, Any],
        width: int,
        height: int,
        remember,
    ) -> Tuple[mpe.VideoClip, float]:
        src = track.get("src")
        if not src:
            raise ValueError("video track missing src")

        clip = remember(VideoFileClip(str(self._resolve_path(src))))

        trim_start = float(track.get("trim_start", 0.0) or 0.0)
        trim_end = float(track.get("trim_end", 0.0) or 0.0)
        duration = clip.duration
        start_t = max(0.0, trim_start)
        end_t = max(start_t + 0.01, duration - max(0.0, trim_end))
        clip = remember(clip.subclip(start_t, end_t))
        clip = remember(clip.without_audio())

        fit = str(track.get("fit", "contain") or "contain").lower()
        clip = remember(self._fit_clip(clip, width, height, fit))

        custom_scale = track.get("scale")
        if custom_scale not in (None, ""):
            clip = remember(clip.resize(float(custom_scale)))

        clip_duration = float(track.get("duration", clip.duration) or clip.duration)
        clip_duration = max(0.1, clip_duration)
        clip = remember(clip.set_duration(clip_duration))
        clip = remember(clip.set_position(self._position(track)))
        return clip, clip_duration

    def _build_image_clip(self, track: Dict[str, Any], remember) -> Tuple[mpe.VideoClip, float]:
        src = track.get("src")
        if not src:
            raise ValueError("image track missing src")

        clip = remember(ImageClip(str(self._resolve_path(src))))
        scale = track.get("scale")
        if scale not in (None, ""):
            clip = remember(clip.resize(float(scale)))

        clip_duration = float(track.get("duration", 3.0) or 3.0)
        clip_duration = max(0.1, clip_duration)
        clip = remember(clip.set_duration(clip_duration))
        clip = remember(clip.set_position(self._position(track)))
        return clip, clip_duration

    def _build_text_clip(self, track: Dict[str, Any], remember) -> Tuple[mpe.VideoClip, float]:
        content = str(track.get("content", "")).strip()
        if not content:
            raise ValueError("text track missing content")

        array = self._render_text_image(track, content)
        clip = remember(ImageClip(array))
        clip_duration = float(track.get("duration", max(2.0, len(content) * 0.08)) or 2.0)
        clip_duration = max(0.5, clip_duration)
        clip = remember(clip.set_duration(clip_duration))
        clip = remember(clip.set_position(self._position(track)))
        return clip, clip_duration

    def _build_audio_clip(
        self,
        track: Dict[str, Any],
        base_duration: float,
        remember,
    ) -> Tuple[mpe.AudioClip, float]:
        src = track.get("src")
        if not src:
            raise ValueError("audio track missing src")

        clip = remember(AudioFileClip(str(self._resolve_path(src))))
        target_duration = track.get("duration")
        if target_duration in (None, ""):
            target_duration = base_duration if base_duration > 0 else clip.duration
        target_duration = float(target_duration)

        loop = bool(track.get("loop", False))
        if loop and target_duration > clip.duration:
            clip = remember(afx.audio_loop(clip, duration=target_duration))
            clip_duration = target_duration
        else:
            clip_duration = min(target_duration, clip.duration)
            clip = remember(clip.subclip(0, clip_duration))

        gain_db = track.get("gain_db")
        if gain_db not in (None, ""):
            factor = 10 ** (float(gain_db) / 20.0)
            clip = remember(clip.volumex(factor))

        return clip, clip_duration

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collect_asset_paths(self, tracks: Sequence[Dict[str, Any]]) -> List[Path]:
        seen: set[Path] = set()
        assets: List[Path] = []
        for track in tracks:
            ttype = (track.get("type") or "").lower()
            if ttype in {"video", "audio", "image"}:
                src = track.get("src")
                if not src:
                    raise ValueError(f"track of type {ttype} missing src")
                path = self._resolve_path(src)
                if path not in seen:
                    assets.append(path)
                    seen.add(path)
            if ttype == "text" and track.get("font"):
                path = self._resolve_path(track["font"])
                if path not in seen:
                    assets.append(path)
                    seen.add(path)
        return assets

    def _write_inputs_hash(
        self,
        work_dir: Path,
        canonical_manifest: Dict[str, Any],
        asset_paths: Sequence[Path],
    ) -> str:
        sha = hashlib.sha256()
        canonical_json = json.dumps(canonical_manifest, sort_keys=True, separators=(",", ":"))
        sha.update(canonical_json.encode("utf-8"))
        if asset_paths:
            sha.update(sha256_of_paths(asset_paths).encode("utf-8"))
        digest = sha.hexdigest()
        (work_dir / "inputs.sha256").write_text(digest, encoding="utf-8")
        return digest

    def _fit_clip(self, clip: mpe.VideoClip, width: int, height: int, mode: str) -> mpe.VideoClip:
        w, h = clip.size
        if not w or not h:
            return clip.resize((width, height))

        mode = mode.lower()
        if mode == "cover":
            scale = max(width / w, height / h)
        elif mode == "scale":
            scale = 1.0
        else:  # contain
            scale = min(width / w, height / h)

        clip = clip.resize(scale)
        return clip

    def _position(self, track: Dict[str, Any]) -> Any:
        x = track.get("x")
        y = track.get("y")
        if x in (None, "") and y in (None, ""):
            return "center"
        return (int(float(x or 0)), int(float(y or 0)))

    def _render_text_image(self, track: Dict[str, Any], content: str) -> np.ndarray:
        font_size = int(track.get("size", 48) or 48)
        font_name = track.get("font")
        font = None
        if font_name:
            font = ImageFont.truetype(str(self._resolve_path(font_name)), font_size)
        else:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except OSError:
                font = ImageFont.load_default()

        lines = content.splitlines() or [""]
        padding = 16
        max_w = 1
        total_h = padding * 2
        line_heights: List[int] = []
        for line in lines:
            if hasattr(font, "getbbox"):
                bbox = font.getbbox(line or " ")  # type: ignore[attr-defined]
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
            else:  # pragma: no cover - legacy Pillow fallback
                width, height = font.getsize(line or " ")
            max_w = max(max_w, width)
            line_heights.append(height)
            total_h += height
        total_h += max(0, len(lines) - 1) * 6

        img = Image.new("RGBA", (max_w + padding * 2, total_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = self._parse_color(track.get("color"), default=(255, 255, 255))
        fill = (*color, 255)
        cursor_y = padding
        for line, height in zip(lines, line_heights):
            draw.text((padding, cursor_y), line, font=font, fill=fill)
            cursor_y += height + 6

        return np.array(img)

    def _parse_color(self, value: Any, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return tuple(int(max(0, min(255, float(v)))) for v in value[:3])  # type: ignore[arg-type]

        if isinstance(value, str):
            text = value.strip()
            if text.startswith("#"):
                text = text[1:]
            if text.lower().startswith("rgb") and "(" in text and ")" in text:
                nums = text[text.find("(") + 1 : text.find(")")].split(",")
                vals = [int(float(n.strip())) for n in nums[:3]]
                return tuple(max(0, min(255, v)) for v in vals)
            if len(text) == 3:
                text = "".join(ch * 2 for ch in text)
            if len(text) == 6:
                try:
                    r = int(text[0:2], 16)
                    g = int(text[2:4], 16)
                    b = int(text[4:6], 16)
                    return (r, g, b)
                except ValueError:
                    pass
        return default

    def _resolve_path(self, src: str) -> Path:
        candidate = Path(str(src)).expanduser()
        search_roots: Iterable[Path] = []
        if candidate.is_absolute():
            search_roots = [candidate]
        else:
            work_dir = self._work_dir or Path.cwd()
            search_roots = [work_dir / candidate, Path.cwd() / candidate]

        for path in search_roots:
            resolved = path.resolve()
            if resolved.exists():
                return resolved

        if candidate.exists():
            return candidate.resolve()

        raise FileNotFoundError(f"Asset not found: {candidate}")

    def _canonicalize(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: self._canonicalize(data[k]) for k in sorted(data)}
        if isinstance(data, list):
            return [self._canonicalize(item) for item in data]
        return data
        # --- keep existing code above ---

# Back-compat alias so imports like `from backend.renderer import Renderer` work
Renderer = VideoComposer

