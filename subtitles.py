# -*- coding: utf-8 -*-
"""
VideoRobot — SubtitleWriter (نسخه کاملاً تمیز)
- تولید ASS با انیمیشن کلمه‌به‌کلمه
- تولید SRT و VTT برای سازگاری
- ساختار تمیز با کلاس‌های جداگانه
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Set, Any, Optional


# ===========================================================================
# کلاس‌های کمکی برای مدیریت رنگ و زمان
# ===========================================================================

class ColorConverter:
    """تبدیل رنگ بین فرمت‌های مختلف"""
    
    _HEX_PATTERN = re.compile(r"^#?[0-9A-Fa-f]{6}$")
    
    @classmethod
    def hex_to_bgr(cls, hex_rgb: str) -> str:
        """
        تبدیل "#RRGGBB" به "BBGGRR" (فرمت ASS)
        مثال: "#FF5733" -> "3357FF"
        """
        if not isinstance(hex_rgb, str):
            return "FFFFFF"  # پیش‌فرض: سفید
        
        h = hex_rgb.strip().lstrip("#")
        
        if not cls._HEX_PATTERN.match("#" + h):
            return "FFFFFF"
        
        rr, gg, bb = h[0:2], h[2:4], h[4:6]
        return f"{bb}{gg}{rr}".upper()
    
    @staticmethod
    def to_ass_color(bgr: str, alpha: str = "00") -> str:
        """
        ساخت رنگ ASS با فرمت &HAABBGGRR&
        alpha: 00=کاملاً مات, FF=کاملاً شفاف
        """
        return f"&H{alpha}{bgr}&"


class TimeFormatter:
    """فرمت‌کننده زمان برای فرمت‌های مختلف زیرنویس"""
    
    # ثابت‌ها
    MS_PER_HOUR = 3_600_000
    MS_PER_MINUTE = 60_000
    MS_PER_SECOND = 1_000
    
    @classmethod
    def to_srt(cls, seconds: float) -> str:
        """HH:MM:SS,mmm (فرمت SRT)"""
        ms = int(round(max(0.0, seconds) * 1000))
        h, r = divmod(ms, cls.MS_PER_HOUR)
        m, r = divmod(r, cls.MS_PER_MINUTE)
        s, ms = divmod(r, cls.MS_PER_SECOND)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    
    @classmethod
    def to_vtt(cls, seconds: float) -> str:
        """HH:MM:SS.mmm (فرمت WebVTT)"""
        return cls.to_srt(seconds).replace(",", ".")
    
    @classmethod
    def to_ass(cls, seconds: float) -> str:
        """H:MM:SS.cc (فرمت ASS - centiseconds)"""
        cs = int(round(max(0.0, seconds) * 100))
        h, r = divmod(cs, 360_000)
        m, r = divmod(r, 6_000)
        s, cs = divmod(r, 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    
    @staticmethod
    def clamp(start: float, end: float, offset: float = 0.0) -> Tuple[float, float]:
        """
        محدود کردن و اصلاح زمان‌ها
        - اضافه کردن offset
        - اطمینان از مثبت بودن
        - حداقل 1ms فاصله
        """
        s = max(0.0, float(start) + offset)
        e = max(0.0, float(end) + offset)
        
        # بررسی اعداد معتبر
        if not math.isfinite(s) or not math.isfinite(e):
            s, e = 0.0, 0.001
        
        # end باید بعد از start باشد
        if e < s:
            e = s + 0.001
        
        # حداقل 1ms فاصله
        if e - s < 0.001:
            e = s + 0.001
        
        return s, e


class TextSanitizer:
    """پاک‌سازی متن برای فرمت‌های مختلف"""
    
    @staticmethod
    def for_ass(text: Any) -> str:
        """
        آماده‌سازی متن برای ASS
        - حذف کاراکترهای کنترلی
        - خنثی کردن {} و \ که در ASS معنی خاص دارند
        """
        s = str(text)
        
        # حذف کاراکترهای کنترلی (به جز \N که در ASS برای خط جدید است)
        s = re.sub(r"[\x00-\x08\x0B-\x1F\x7F]", "", s)
        
        # خنثی‌سازی کاراکترهای خاص
        s = s.replace("\\", "⧵")  # Backslash
        s = s.replace("{", "(")   # آکولاد باز
        s = s.replace("}", ")")   # آکولاد بسته
        
        return s.strip()
    
    @staticmethod
    def for_plain(text: Any) -> str:
        """
        پاک‌سازی ساده برای SRT/VTT
        - حذف \r و \t
        - فشرده کردن فضاهای خالی
        """
        s = str(text)
        s = s.replace("\r", " ").replace("\t", " ")
        s = re.sub(r"\s+", " ", s)
        return s.strip()


# ===========================================================================
# مدل‌های داده
# ===========================================================================

@dataclass
class Word:
    """یک کلمه با زمان شروع و پایان"""
    start: float
    end: float
    text: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional['Word']:
        """ساخت از دیکشنری با اعتبارسنجی"""
        try:
            s = float(data["s"])
            e = float(data["e"])
            raw = str(data.get("raw", ""))
            
            if not math.isfinite(s) or not math.isfinite(e):
                return None
            
            # اصلاح end اگر قبل از start بود
            if e < s:
                e = s
            
            return cls(start=s, end=e, text=raw)
        except (KeyError, ValueError, TypeError):
            return None
    
    def is_sentence_end(self) -> bool:
        """آیا این کلمه پایان جمله است؟"""
        return self.text.endswith((".", "?", "!"))
    
    def normalized_text(self) -> str:
        """متن نرمال شده برای مقایسه (حذف علائم نگارشی)"""
        return self.text.strip(".,?!'\"").lower()


@dataclass
class CaptionConfig:
    """تنظیمات نمایش زیرنویس"""
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
        """ساخت از شیء config"""
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
        تبدیل موقعیت به شماره alignment ASS (numpad style)
        8 = بالا، 5 = وسط، 2 = پایین
        """
        alignment_map = {
            "Top": 8,
            "Middle": 5,
            "Bottom": 2,
        }
        return alignment_map.get(self.position, 2)


# ===========================================================================
# تقسیم‌کننده متن به بخش‌های قابل نمایش
# ===========================================================================

class CaptionSegmenter:
    """تقسیم کلمات به جملات و سپس به بخش‌های قابل نمایش"""
    
    def __init__(self, config: CaptionConfig):
        self.config = config
    
    def segment(self, words: List[Word]) -> List[List[Word]]:
        """
        تقسیم به chunks مناسب برای نمایش
        1. تقسیم به جملات
        2. تقسیم جملات طولانی به chunks
        """
        sentences = self._split_into_sentences(words)
        chunks = self._split_into_chunks(sentences)
        return chunks
    
    def _split_into_sentences(self, words: List[Word]) -> List[List[Word]]:
        """تقسیم بر اساس علائم نگارشی پایان جمله"""
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
        """تقسیم جملات به chunks بر اساس طول و زمان"""
        chunks: List[List[Word]] = []
        
        for sentence in sentences:
            current_chunk: List[Word] = []
            
            for word in sentence:
                current_chunk.append(word)
                
                # بررسی محدودیت‌ها
                duration_ms = int((current_chunk[-1].end - current_chunk[0].start) * 1000)
                
                if (len(current_chunk) >= self.config.max_words_per_caption or 
                    duration_ms >= self.config.max_caption_ms):
                    chunks.append(current_chunk)
                    current_chunk = []
            
            if current_chunk:
                chunks.append(current_chunk)
        
        return chunks


# ===========================================================================
# سازنده‌های فایل زیرنویس
# ===========================================================================

class ASSBuilder:
    """ساخت فایل ASS با انیمیشن"""
    
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
        """ساخت محتوای کامل فایل ASS"""
        lines = [
            self._build_header(),
            self._build_events_header(),
        ]
        
        for chunk in chunks:
            lines.append(self._build_dialogue(chunk, keywords, ts_offset))
        
        return "".join(lines)
    
    def _build_header(self) -> str:
        """بخش Script Info و Styles"""
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
        """هدر بخش Events"""
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
        """ساخت یک خط Dialogue با انیمیشن کلمه‌به‌کلمه"""
        if not chunk:
            return ""
        
        # زمان شروع و پایان کل caption
        start_time, end_time = self.time.clamp(chunk[0].start, chunk[-1].end, ts_offset)
        chunk_start = chunk[0].start  # مرجع محلی برای محاسبات نسبی
        
        # تقسیم به خطوط بر اساس max_words_per_line
        display_lines = self._split_into_display_lines(chunk)
        
        # ساخت متن با انیمیشن برای هر خط
        animated_lines = []
        for line_words in display_lines:
            line_text = self._animate_line(line_words, keywords, chunk_start)
            animated_lines.append(line_text)
        
        # ترکیب خطوط با \N (newline در ASS)
        full_text = "\\N".join(animated_lines)
        
        return (
            f"Dialogue: 0,"
            f"{self.time.to_ass(start_time)},"
            f"{self.time.to_ass(end_time)},"
            f"Default,,0,0,0,,"
            f"{full_text}\n"
        )
    
    def _split_into_display_lines(self, chunk: List[Word]) -> List[List[Word]]:
        """تقسیم chunk به خطوط نمایشی"""
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
        """ساخت انیمیشن برای یک خط"""
        word_tags: List[str] = []
        
        for word in words:
            # محاسبه زمان نسبی (میلی‌ثانیه)
            start_ms = max(0, int((word.start - chunk_start) * 1000))
            end_ms = max(start_ms + 1, int((word.end - chunk_start) * 1000))
            
            # انتخاب رنگ هایلایت
            is_keyword = word.normalized_text() in keywords
            highlight_color = (self.config.keyword_color if is_keyword 
                             else self.config.active_color)
            bgr = self.color.hex_to_bgr(highlight_color)
            
            # متن ایمن‌شده
            safe_text = self.text.for_ass(word.text)
            
            # ساخت تگ‌های انیمیشن:
            # 1. شروع سفید
            # 2. تغییر به رنگ هایلایت در [start_ms, end_ms]
            # 3. برگشت به سفید در [end_ms, end_ms+1]
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
    """ساخت فایل SRT ساده"""
    
    def __init__(self):
        self.time = TimeFormatter()
        self.text = TextSanitizer()
    
    def build(self, chunks: List[List[Word]], ts_offset: float) -> str:
        """ساخت محتوای کامل فایل SRT"""
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
    """ساخت فایل WebVTT"""
    
    def __init__(self):
        self.time = TimeFormatter()
        self.text = TextSanitizer()
    
    def build(self, chunks: List[List[Word]], ts_offset: float) -> str:
        """ساخت محتوای کامل فایل VTT"""
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
# کلاس اصلی SubtitleWriter
# ===========================================================================

class SubtitleWriter:
    """
    تولید فایل‌های زیرنویس ASS, SRT, VTT
    
    ASS: با انیمیشن کلمه‌به‌کلمه و استایل پیشرفته
    SRT: فرمت ساده و سازگار
    VTT: برای پخش وب
    """
    
    def __init__(self, tmp: Path, out_dir: Path) -> None:
        if not isinstance(tmp, Path) or not isinstance(out_dir, Path):
            raise TypeError("tmp و out_dir باید Path باشند")
        
        self.tmp = tmp
        self.out = out_dir
        
        # ایجاد پوشه‌ها
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
    
    def write(
        self,
        words: List[Dict[str, Any]],
        cfg,  # CaptionCfg شیء
        kws: Set[str],
        ts_off: float,
        stem: str,
        playresx: int,
        playresy: int,
    ) -> Tuple[Path, Path]:
        """
        تولید فایل‌های زیرنویس
        
        Args:
            words: لیست کلمات با {"s": float, "e": float, "raw": str}
            cfg: تنظیمات caption
            kws: مجموعه کلمات کلیدی برای هایلایت
            ts_off: offset زمانی
            stem: نام پایه فایل
            playresx, playresy: ابعاد ویدئو
        
        Returns:
            (ass_path, srt_path): مسیر فایل‌های تولید شده
        """
        # نرمال‌سازی ورودی‌ها
        config = CaptionConfig.from_cfg(cfg)
        keywords = {str(x).lower() for x in (kws or set())}
        ts_offset = float(ts_off or 0.0)
        stem = str(stem)
        
        # مسیرهای خروجی
        srt_path = self.out / f"{stem}.srt"
        vtt_path = self.out / f"{stem}.vtt"
        ass_path = self.tmp / "subs.ass"
        
        # حالت خالی: فایل‌های خالی
        if not words:
            return self._write_empty_files(srt_path, vtt_path, ass_path, playresx, playresy, config)
        
        # تبدیل به مدل Word
        word_objects = self._parse_words(words)
        if not word_objects:
            return self._write_empty_files(srt_path, vtt_path, ass_path, playresx, playresy, config)
        
        # تقسیم به chunks
        segmenter = CaptionSegmenter(config)
        chunks = segmenter.segment(word_objects)
        
        # ساخت فایل‌ها
        self._write_ass(ass_path, chunks, keywords, ts_offset, config, playresx, playresy)
        self._write_srt(srt_path, chunks, ts_offset)
        self._write_vtt(vtt_path, chunks, ts_offset)
        
        return ass_path, srt_path
    
    def _parse_words(self, words: List[Dict[str, Any]]) -> List[Word]:
        """تبدیل دیکشنری‌ها به اشیاء Word با اعتبارسنجی"""
        word_objects: List[Word] = []
        
        for w in words:
            word = Word.from_dict(w)
            if word:
                word_objects.append(word)
        
        # مرتب‌سازی بر اساس زمان شروع
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
        """ساخت فایل‌های خالی"""
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
        """نوشتن فایل ASS"""
        builder = ASSBuilder(config, playresx, playresy)
        content = builder.build(chunks, keywords, ts_offset)
        path.write_text(content, encoding="utf-8")
    
    def _write_srt(self, path: Path, chunks: List[List[Word]], ts_offset: float):
        """نوشتن فایل SRT"""
        builder = SRTBuilder()
        content = builder.build(chunks, ts_offset)
        path.write_text(content, encoding="utf-8")
    
    def _write_vtt(self, path: Path, chunks: List[List[Word]], ts_offset: float):
        """نوشتن فایل VTT"""
        builder = VTTBuilder()
        content = builder.build(chunks, ts_offset)
        path.write_text(content, encoding="utf-8")