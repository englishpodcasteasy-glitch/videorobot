# -*- coding: utf-8 -*-
"""
VideoRobot — SubtitleWriter (Clean and Corrected Version)
- Generates ASS with word-by-word animation
- Generates SRT and VTT for compatibility
- Clean structure with separate classes
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Set, Any, Optional


# ===========================================================================
# Helper classes for color and time management
# ===========================================================================

class ColorConverter:
    """Converts colors between different formats"""
    
    # Use a raw string (r"...") for regex patterns to avoid escape sequence warnings
    _HEX_PATTERN = re.compile(r"^#?[0-9A-Fa-f]{6}$")
    
    @classmethod
    def hex_to_bgr(cls, hex_rgb: str) -> str:
        """
        Converts "#RRGGBB" to "BBGGRR" (ASS format)
        Example: "#FF5733" -> "3357FF"
        """
        if not isinstance(hex_rgb, str):
            return "FFFFFF"  # Default: white
        
        h = hex_rgb.strip().lstrip("#")
        
        # Use a raw string for the "#" character to be safe
        if not cls._HEX_PATTERN.match(r"#" + h):
            return "FFFFFF"
        
        rr, gg, bb = h[0:2], h[2:4], h[4:6]
        return f"{bb}{gg}{rr}".upper()
    
    @staticmethod
    def to_ass_color(bgr: str, alpha: str = "00") -> str:
        """
        Creates an ASS color with format &HAABBGGRR&
        alpha: 00=fully opaque, FF=fully transparent
        """
        return f"&H{alpha}{bgr}&"


class TimeFormatter:
    """Formats time for different subtitle formats"""
    
    # Constants
    MS_PER_HOUR = 3_600_000
    MS_PER_MINUTE = 60_000
    MS_PER_SECOND = 1_000
    
    @classmethod
    def to_srt(cls, seconds: float) -> str:
        """HH:MM:SS,mmm (SRT format)"""
        ms = int(round(max(0.0, seconds) * 1000))
        h, r = divmod(ms, cls.MS_PER_HOUR)
        m, r = divmod(r, cls.MS_PER_MINUTE)
        s, ms = divmod(r, cls.MS_PER_SECOND)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    
    @classmethod
    def to_vtt(cls, seconds: float) -> str:
        """HH:MM:SS.mmm (WebVTT format)"""
        return cls.to_srt(seconds).replace(",", ".")
    
    @classmethod
    def to_ass(cls, seconds: float) -> str:
        """H:MM:SS.cc (ASS format - centiseconds)"""
        cs = int(round(max(0.0, seconds) * 100))
        h, r = divmod(cs, 360_000)
        m, r = divmod(r, 6_000)
        s, cs = divmod(r, 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    
    @staticmethod
    def clamp(start: float, end: float, offset: float = 0.0) -> Tuple[float, float]:
        """
        Clamps and corrects times
        - Adds offset
        - Ensures they are positive
        - Ensures at least 1ms duration
        """
        s = max(0.0, float(start) + offset)
        e = max(0.0, float(end) + offset)
        
        # Check for valid numbers
        if not math.isfinite(s) or not math.isfinite(e):
            s, e = 0.0, 0.001
        
        # end must be after start
        if e < s:
            e = s + 0.001
        
        # Minimum 1ms duration
        if e - s < 0.001:
            e = s + 0.001
        
        return s, e


class TextSanitizer:
    """Sanitizes text for different formats"""
    
    @staticmethod
    def for_ass(text: Any) -> str:
        """
        Prepares text for ASS format
        - Removes control characters
        - Escapes {} and \ which have special meaning in ASS
        """
        s = str(text)
        
        # Remove control characters (except \N which is a newline in ASS)
        s = re.sub(r"[\x00-\x08\x0B-\x1F\x7F]", "", s)
        
        # Escape special characters
        # FIX: Use a raw string r"\" to represent a single backslash
        s = s.replace(r"\", "⧵")  # Backslash
        s = s.replace("{", "(")   # Open brace
        s = s.replace("}", ")")   # Close brace
        
        return s.strip()
    
    @staticmethod
    def for_plain(text: Any) -> str:
        """
        Simple sanitization for SRT/VTT
        - Removes \r and \t
        - Collapses whitespace
        """
        s = str(text)
        s = s.replace("\r", " ").replace("\t", " ")
        s = re.sub(r"\s+", " ", s)
        return s.strip()


# ===========================================================================
# Data Models
# ===========================================================================

@dataclass
class Word:
    """A word with a start and end time"""
    start: float
    end: float
    text: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional['Word']:
        """Creates from a dictionary with validation"""
        try:
            s = float(data["s"])
            e = float(data["e"])
            raw = str(data.get("raw", ""))
            
            if not math.isfinite(s) or not math.isfinite(e):
                return None
            
            # Correct end if it's before start
            if e < s:
                e = s
            
            return cls(start=s, end=e, text=raw)
        except (KeyError, ValueError, TypeError):
            return None
    
    def is_sentence_end(self) -> bool:
        """Is this word the end of a sentence?"""
        return self.text.endswith((".", "?", "!"))
    
    def normalized_text(self) -> str:
        """Normalized text for comparison (removes punctuation)"""
        return self.text.strip(".,?!'\"").lower()


@dataclass
class CaptionConfig:
    """Subtitle display settings"""
    font_name: str = "DejaVu Sans"
    font_size: int = 48
    active_color: str = "#FFFFFF"
    keyword_color: str = "#00FFFF"
    border_thickness: int = 2
    max_words_per_line: int = 6
    max_words_per_caption: int = 8
    max_caption_ms: int = 4500
    position: str = "Bottom"  # Top, Middle, Bottom
    margin_v: int = 80
    
    @classmethod
    def from_cfg(cls, cfg) -> 'CaptionConfig':
        """Creates from a config object"""
        return cls(
            font_name=getattr(cfg, "font_name", cls.font_name),
            font_size=int(getattr(cfg, "font_size", cls.font_size)),
            active_color=getattr(cfg, "active_color", cls.active_color),
            keyword_color=getattr(cfg, "keyword_color", cls.keyword_color),
            border_thickness=max(2, int(getattr(cfg, "border_thickness", cls.border_thickness))),
            max_words_per_line=max(1, int(getattr(cfg, "max_words_per_line", cls.max_words_per_line))),
            max_words_per_caption=max(1, int(getattr(cfg, "max_words_per_caption", cls.max_words_per_caption))),
            max_caption_ms=int(getattr(cfg, "max_caption_ms", cls.max_caption_ms)),
            position=str(getattr(getattr(cfg, "position", "Bottom"), "value", "Bottom")),
            margin_v=int(getattr(cfg, "margin_v", cls.margin_v)),
        )
    
    def get_alignment(self) -> int:
        """
        Converts position to ASS alignment number (numpad style)
        8 = top, 5 = middle, 2 = bottom
        """
        alignment_map = {
            "Top": 8,
            "Middle": 5,
            "Bottom": 2,
        }
        return alignment_map.get(self.position, 2)


# ===========================================================================
# Text Segmenter
# ===========================================================================

class CaptionSegmenter:
    """Segments words into sentences and then into displayable chunks"""
    
    def __init__(self, config: CaptionConfig):
        self.config = config
    
    def segment(self, words: List[Word]) -> List[List[Word]]:
        """
        Segments into chunks suitable for display
        1. Splits into sentences
        2. Splits long sentences into chunks
        """
        sentences = self._split_into_sentences(words)
        chunks = self._split_into_chunks(sentences)
        return chunks
    
    def _split_into_sentences(self, words: List[Word]) -> List[List[Word]]:
        """Splits based on sentence-ending punctuation"""
        sentences: List[List[Word]] = []
        current: List[Word] = []
        
        for word in words:
            current.append(word)
            if word.is_sentence_end():
                sentences.append(current)
                current = []
        
        if current:
            sentences.append(current)
        
        return sentences
    
    def _split_into_chunks(self, sentences: List[List[Word]]) -> List[List[Word]]:
        """Splits sentences into chunks based on length and time"""
        chunks: List[List[Word]] = []
        
        for sentence in sentences:
            current_chunk: List[Word] = []
            
            for word in sentence:
                current_chunk.append(word)
                
                # Check limits
                duration_ms = int((current_chunk[-1].end - current_chunk[0].start) * 1000)
                
                if (len(current_chunk) >= self.config.max_words_per_caption or 
                    duration_ms >= self.config.max_caption_ms):
                    chunks.append(current_chunk)
                    current_chunk = []
            
            if current_chunk:
                chunks.append(current_chunk)
        
        return chunks


# ===========================================================================
# Subtitle File Builders
# ===========================================================================

class ASSBuilder:
    """Builds ASS files with animation"""
    
    def __init__(self, config: CaptionConfig, playresx: int, playresy: int):
        self.config = config
        self.playresx = playresx
        self.playresy = playresy
        self.color = ColorConverter()
        self.time = TimeFormatter()
        self.text = TextSanitizer()
    
    def build(
        self, 
        chunks: List[List[Word]], 
        keywords: Set[str],
        ts_offset: float
    ) -> str:
        """Builds the complete ASS file content"""
        lines = [
            self._build_header(),
            self._build_events_header(),
        ]
        
        for chunk in chunks:
            lines.append(self._build_dialogue(chunk, keywords, ts_offset))
        
        return "".join(lines)
    
    def _build_header(self) -> str:
        """Builds the Script Info and Styles section"""
        align = self.config.get_alignment()
        
        return (
            "[Script Info]\n"
            "Title: VideoRobot Subtitles\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.playresx}\n"
            f"PlayResY: {self.playresy}\n"
            "WrapStyle: 1\n"
            "ScaledBorderAndShadow: yes\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{self.config.font_name},{self.config.font_size},"
            f"&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
            f"-1,0,0,0,100,100,0,0,1,{self.config.border_thickness},3,"
            f"{align},80,80,{self.config.margin_v},1\n"
            "\n"
        )
    
    def _build_events_header(self) -> str:
        """Builds the Events section header"""
        return (
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
    
    def _build_dialogue(
        self, 
        chunk: List[Word],
        keywords: Set[str],
        ts_offset: float
    ) -> str:
        """Builds a single Dialogue line with word-by-word animation"""
        if not chunk:
            return ""
        
        # Start and end time for the whole caption
        start_time, end_time = self.time.clamp(chunk[0].start, chunk[-1].end, ts_offset)
        chunk_start = chunk[0].start  # Local reference for relative calculations
        
        # Split into lines based on max_words_per_line
        display_lines = self._split_into_display_lines(chunk)
        
        # Build animated text for each line
        animated_lines = []
        for line_words in display_lines:
            line_text = self._animate_line(line_words, keywords, chunk_start)
            animated_lines.append(line_text)
        
        # Combine lines with \N (newline in ASS)
        full_text = "\\N".join(animated_lines)
        
        return (
            f"Dialogue: 0,"
            f"{self.time.to_ass(start_time)},"
            f"{self.time.to_ass(end_time)},"
            f"Default,,0,0,0,,"
            f"{full_text}\n"
        )
    
    def _split_into_display_lines(self, chunk: List[Word]) -> List[List[Word]]:
        """Splits a chunk into display lines"""
        lines: List[List[Word]] = []
        current_line: List[Word] = []
        
        for word in chunk:
            current_line.append(word)
            if len(current_line) >= self.config.max_words_per_line:
                lines.append(current_line)
                current_line = []
        
        if current_line:
            lines.append(current_line)
        
        return lines
    
    def _animate_line(
        self, 
        words: List[Word],
        keywords: Set[str],
        chunk_start: float
    ) -> str:
        """Builds animation for a single line"""
        word_tags: List[str] = []
        
        for word in words:
            # Calculate relative time (milliseconds)
            start_ms = max(0, int((word.start - chunk_start) * 1000))
            end_ms = max(start_ms + 1, int((word.end - chunk_start) * 1000))
            
            # Choose highlight color
            is_keyword = word.normalized_text() in keywords
            highlight_color = (self.config.keyword_color if is_keyword 
                             else self.config.active_color)
            bgr = self.color.hex_to_bgr(highlight_color)
            
            # Sanitized text
            safe_text = self.text.for_ass(word.text)
            
            # Build animation tags:
            # 1. Start white
            # 2. Change to highlight color in [start_ms, end_ms]
            # 3. Return to white in [end_ms, end_ms+1]
            tag = (
                f"{{\\bord{self.config.border_thickness}}}"
                f"{{\\1c&HFFFFFF&}}"
                f"{{\\t({start_ms},{end_ms},\\1c&H{bgr}&)}}"
                f"{{\\t({end_ms},{end_ms + 1},\\1c&HFFFFFF&)}}"
                f"{safe_text} "
            )
            word_tags.append(tag)
        
        return "".join(word_tags).strip()


class SRTBuilder:
    """Builds simple SRT files"""
    
    def __init__(self):
        self.time = TimeFormatter()
        self.text = TextSanitizer()
    
    def build(self, chunks: List[List[Word]], ts_offset: float) -> str:
        """Builds the complete SRT file content"""
        lines: List[str] = []
        
        for i, chunk in enumerate(chunks, start=1):
            start_time, end_time = self.time.clamp(
                chunk[0].start, 
                chunk[-1].end, 
                ts_offset
            )
            
            text = self.text.for_plain(" ".join(w.text for w in chunk))
            
            lines.append(
                f"{i}\n"
                f"{self.time.to_srt(start_time)} --> {self.time.to_srt(end_time)}\n"
                f"{text}\n\n"
            )
        
        return "".join(lines)


class VTTBuilder:
    """Builds WebVTT files"""
    
    def __init__(self):
        self.time = TimeFormatter()
        self.text = TextSanitizer()
    
    def build(self, chunks: List[List[Word]], ts_offset: float) -> str:
        """Builds the complete VTT file content"""
        lines = ["WEBVTT\n\n"]
        
        for chunk in chunks:
            start_time, end_time = self.time.clamp(
                chunk[0].start,
                chunk[-1].end,
                ts_offset
            )
            
            text = self.text.for_plain(" ".join(w.text for w in chunk))
            
            lines.append(
                f"{self.time.to_vtt(start_time)} --> {self.time.to_vtt(end_time)}\n"
                f"{text}\n\n"
            )
        
        return "".join(lines)


# ===========================================================================
# Main SubtitleWriter Class
# ===========================================================================

class SubtitleWriter:
    """
    Generates ASS, SRT, VTT subtitle files
    
    ASS: With word-by-word animation and advanced styling
    SRT: Simple and compatible format
    VTT: For web playback
    """
    
    def __init__(self, tmp: Path, out_dir: Path) -> None:
        if not isinstance(tmp, Path) or not isinstance(out_dir, Path):
            raise TypeError("tmp and out_dir must be Path objects")
        
        self.tmp = tmp
        self.out = out_dir
        
        # Create directories
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
    
    def write(
        self,
        words: List[Dict[str, Any]],
        cfg,  # CaptionCfg object
        kws: Set[str],
        ts_off: float,
        stem: str,
        playresx: int,
        playresy: int,
    ) -> Tuple[Path, Path]:
        """
        Generates subtitle files
        
        Args:
            words: List of words with {"s": float, "e": float, "raw": str}
            cfg: Caption settings
            kws: Set of keywords for highlighting
            ts_off: Time offset
            stem: Base file name
            playresx, playresy: Video dimensions
        
        Returns:
            (ass_path, srt_path): Paths to the generated files
        """
        # Normalize inputs
        config = CaptionConfig.from_cfg(cfg)
        keywords = {str(x).lower() for x in (kws or set())}
        ts_offset = float(ts_off or 0.0)
        stem = str(stem)
        
        # Output paths
        srt_path = self.out / f"{stem}.srt"
        vtt_path = self.out / f"{stem}.vtt"
        ass_path = self.tmp / "subs.ass"
        
        # Empty case: create empty files
        if not words:
            return self._write_empty_files(srt_path, vtt_path, ass_path, playresx, playresy, config)
        
        # Convert to Word model
        word_objects = self._parse_words(words)
        if not word_objects:
            return self._write_empty_files(srt_path, vtt_path, ass_path, playresx, playresy, config)
        
        # Segment into chunks
        segmenter = CaptionSegmenter(config)
        chunks = segmenter.segment(word_objects)
        
        # Build files
        self._write_ass(ass_path, chunks, keywords, ts_offset, config, playresx, playresy)
        self._write_srt(srt_path, chunks, ts_offset)
        self._write_vtt(vtt_path, chunks, ts_offset)
        
        return ass_path, srt_path
    
    def _parse_words(self, words: List[Dict[str, Any]]) -> List[Word]:
        """Converts dictionaries to Word objects with validation"""
        word_objects: List[Word] = []
        
        for w in words:
            word = Word.from_dict(w)
            if word:
                word_objects.append(word)
        
        # Sort by start time
        word_objects.sort(key=lambda x: x.start)
        
        return word_objects
    
    def _write_empty_files(
        self,
        srt_path: Path,
        vtt_path: Path,
        ass_path: Path,
        playresx: int,
        playresy: int,
        config: CaptionConfig
    ) -> Tuple[Path, Path]:
        """Creates empty files"""
        srt_path.write_text("", encoding="utf-8")
        vtt_path.write_text("WEBVTT\n\n", encoding="utf-8")
        
        ass_builder = ASSBuilder(config, playresx, playresy)
        ass_path.write_text(ass_builder._build_header(), encoding="utf-8")
        
        return ass_path, srt_path
    
    def _write_ass(
        self,
        path: Path,
        chunks: List[List[Word]],
        keywords: Set[str],
        ts_offset: float,
        config: CaptionConfig,
        playresx: int,
        playresy: int
    ):
        """Writes the ASS file"""
        builder = ASSBuilder(config, playresx, playresy)
        content = builder.build(chunks, keywords, ts_offset)
        path.write_text(content, encoding="utf-8")
    
    def _write_srt(self, path: Path, chunks: List[List[Word]], ts_offset: float):
        """Writes the SRT file"""
        builder = SRTBuilder()
        content = builder.build(chunks, ts_offset)
        path.write_text(content, encoding="utf-8")
    
    def _write_vtt(self, path: Path, chunks: List[List[Word]], ts_offset: float):
        """Writes the VTT file"""
        builder = VTTBuilder()
        content = builder.build(chunks, ts_offset)
        path.write_text(content, encoding="utf-8")
