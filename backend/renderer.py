# -*- coding: utf-8 -*-
"""
VideoRobot — Renderer (نسخه کاملاً تمیز)
همه مشکلات برطرف شده + ساختار بهتر
"""
from __future__ import annotations

import datetime
import logging
import shlex
import shutil
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

from .config import ProjectCfg, FONTS
from .scheduler import Scheduler
from .subtitles import SubtitleWriter
from .audio_processor import AudioProcessor
from .utils import (
    build_fonts_only,
    sanitize_filename,
    sh,
    pick_default_font_name,
    hex_to_0xRRGGBB,
)

log = logging.getLogger("VideoRobot.renderer")


# ---------------------------------------------------------------------------
# تنظیمات پیش‌فرض (قابل تغییر از config)
# ---------------------------------------------------------------------------
@dataclass
class RenderDefaults:
    fps: int = 30
    ken_burns_zoom: float = 1.10
    audio_bitrate: str = "192k"
    video_crf: int = 23
    max_duration: float = 3600.0  # 1 ساعت
    min_duration: float = 0.1


# ---------------------------------------------------------------------------
# ساخت فیلتر گراف (کلاس جداگانه برای تمیزی)
# ---------------------------------------------------------------------------
class FilterGraphBuilder:
    """سازنده فیلتر گراف FFmpeg به صورت گام‌به‌گام"""
    
    def __init__(self, width: int, height: int):
        self.W = width
        self.H = height
        self.filters: List[str] = []
        self._counter = 0
        self._current = None
    
    def _next_label(self) -> str:
        """برچسب یکتا برای هر مرحله"""
        label = f"v{self._counter}"
        self._counter += 1
        return label
    
    def add_base(self, input_idx: int, filter_expr: str) -> 'FilterGraphBuilder':
        """افزودن فیلتر پایه (background با Ken Burns)"""
        label = self._next_label()
        self.filters.append(f"[{input_idx}:v]{filter_expr}[{label}]")
        self._current = label
        return self
    
    def add_scaled_input(self, input_idx: int, label: str) -> 'FilterGraphBuilder':
        """افزودن ورودی مقیاس‌شده (برای intro/outro/cta)"""
        self.filters.append(
            f"[{input_idx}:v]scale={self.W}:{self.H},format=rgba,setpts=PTS-STARTPTS[{label}]"
        )
        return self
    
    def overlay(self, overlay_label: str, enable_expr: Optional[str] = None) -> 'FilterGraphBuilder':
        """اضافه کردن لایه روی ویدئو"""
        out_label = self._next_label()
        enable_part = f":enable='{enable_expr}'" if enable_expr else ""
        self.filters.append(
            f"[{self._current}][{overlay_label}]overlay{enable_part}[{out_label}]"
        )
        self._current = out_label
        return self
    
    def chromakey_overlay(
        self, 
        input_idx: int, 
        key_color: str,
        similarity: float,
        blend: float,
        enable_expr: str
    ) -> 'FilterGraphBuilder':
        """CTA با حذف پس‌زمینه سبز"""
        cta_label = "vcta"
        keycol = hex_to_0xRRGGBB(key_color)
        self.filters.append(
            f"[{input_idx}:v]scale={self.W}:{self.H},format=rgba,"
            f"chromakey={keycol}:{similarity}:{blend}[{cta_label}]"
        )
        return self.overlay(cta_label, enable_expr)
    
    def burn_subtitles(
        self, 
        ass_path: Path, 
        fonts_dir: Path,
        font_name: str,
        margin_v: int
    ) -> 'FilterGraphBuilder':
        """سوزاندن زیرنویس روی ویدئو"""
        sub_label = self._next_label()
        self.filters.append(
            f"[{self._current}]subtitles={shlex.quote(str(ass_path))}:"
            f"fontsdir={shlex.quote(str(fonts_dir))}:"
            f"force_style='FontName={font_name},MarginV={margin_v}'[{sub_label}]"
        )
        self._current = sub_label
        return self
    
    def finalize(self, output_label: str = "vout") -> str:
        """نهایی‌سازی با format و برگشت filter_complex"""
        self.filters.append(f"[{self._current}]format=yuv420p[{output_label}]")
        return ";".join(self.filters)


# ---------------------------------------------------------------------------
# مدیریت ورودی‌ها
# ---------------------------------------------------------------------------
class InputManager:
    """مدیریت فایل‌های ورودی و ایندکس‌گذاری"""
    
    def __init__(self, paths, cfg: ProjectCfg):
        self.paths = paths
        self.cfg = cfg
        self.inputs: List[str] = []
        self.index: Dict[str, int] = {}
        self._current_idx = 0
    
    def add_background(self, bg_file: Path) -> 'InputManager':
        """اضافه کردن تصویر پس‌زمینه (با loop)"""
        self.inputs.extend([
            "-loop", "1", 
            "-framerate", "30",  # TODO: از config بگیر
            "-i", str(bg_file)
        ])
        self.index["bg"] = self._current_idx
        self._current_idx += 1
        return self
    
    def add_audio(self, audio_file: Path) -> 'InputManager':
        """اضافه کردن صدا"""
        self.inputs.extend(["-i", str(audio_file)])
        self.index["audio"] = self._current_idx
        self._current_idx += 1
        return self
    
    def add_optional(self, name: str, file_path: Optional[Path]) -> 'InputManager':
        """اضافه کردن فایل اختیاری (intro/outro/cta)"""
        if file_path and file_path.exists():
            self.inputs.extend(["-i", str(file_path)])
            self.index[name] = self._current_idx
            self._current_idx += 1
        return self
    
    def get_inputs(self) -> List[str]:
        return self.inputs
    
    def get_index(self) -> Dict[str, int]:
        return self.index


# ---------------------------------------------------------------------------
# FFmpeg Commander (بدون تغییر)
# ---------------------------------------------------------------------------
class FFmpegCommander:
    _has_libass: bool | None = None

    @staticmethod
    def has_nvenc() -> bool:
        try:
            out = sh(["ffmpeg", "-hide_banner", "-encoders"], "Probe encoders", check=False)
            txt = (out.stdout or "") + (out.stderr or "")
            return ("h264_nvenc" in txt) or ("hevc_nvenc" in txt)
        except Exception:
            return False

    @staticmethod
    def probe_duration(p: Path | None) -> float:
        if p is None or not isinstance(p, Path) or not p.exists():
            return 0.0
        try:
            proc = sh(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(p)],
                "Probe duration",
                check=True,
            )
            s = (proc.stdout or "").strip()
            return float(s) if s else 0.0
        except Exception:
            return 0.0

    @classmethod
    def has_libass(cls) -> bool:
        if cls._has_libass is None:
            try:
                res = sh(["ffmpeg", "-hide_banner", "-filters"], "Probe filters", check=False)
                txt = (res.stdout or "") + (res.stderr or "")
                cls._has_libass = any(k in txt for k in ("subtitles", "ass", "libass"))
            except Exception:
                cls._has_libass = False
        return bool(cls._has_libass)


# ---------------------------------------------------------------------------
# Renderer اصلی (تمیز شده)
# ---------------------------------------------------------------------------
class Renderer:
    def __init__(self, paths) -> None:
        self.paths = paths
        self.scheduler = Scheduler()
        self.subs = SubtitleWriter(paths.tmp, paths.out_local)
        self.aproc = AudioProcessor(paths.tmp)
        self.defaults = RenderDefaults()

    def _build_ken_burns(self, W: int, H: int, dur: float, fps: int) -> str:
        """ساخت فیلتر Ken Burns با استفاده از on"""
        zoom = self.defaults.ken_burns_zoom
        frames = max(2, int(round(dur * fps)))
        denom = frames - 1
        
        expr_x = f"on/{denom}*(iw - iw/{zoom})"
        expr_y = f"-on/{denom}*(ih - ih/{zoom})"
        
        return (
            f"scale={int(W*zoom)}:{int(H*zoom)},"
            f"zoompan=z={zoom}:d={frames}:x='{expr_x}':y='{expr_y}':s={W}x{H}"
        )

    def _validate_audio(self, audio_file: Path, cfg: ProjectCfg) -> Tuple[Path, float]:
        """نرمال‌سازی و اعتبارسنجی صدا"""
        if not audio_file.exists():
            raise FileNotFoundError(f"❌ فایل صدا پیدا نشد: {audio_file}")
        
        norm_audio = self.aproc.normalize(audio_file, cfg.audio)
        duration = FFmpegCommander.probe_duration(norm_audio)
        
        if duration < self.defaults.min_duration:
            raise RuntimeError(f"❌ صدا خیلی کوتاه است: {duration:.2f}s")
        if duration > self.defaults.max_duration:
            raise RuntimeError(f"❌ صدا خیلی طولانی است: {duration:.2f}s")
        
        log.info(f"✅ صدا آماده شد: {duration:.2f}s")
        return Path(norm_audio), duration

    def _prepare_subtitles(
        self, 
        norm_audio: Path, 
        cfg: ProjectCfg,
        W: int,
        H: int
    ) -> Tuple[Path, Path, set]:
        """رونویسی، استخراج کلمات کلیدی و ساخت زیرنویس"""
        # رونویسی
        words = self.scheduler.transcribe_words(
            norm_audio,
            size=cfg.audio.whisper_model,
            use_vad=cfg.audio.use_vad,
        )
        
        # استخراج کلمات کلیدی
        full_text = " ".join(w["raw"] for w in words)
        kws_list = self.scheduler.extract_keywords(
            full_text, 
            topk=16, 
            ngram_max=1, 
            dedup_lim=0.9
        )
        kws = {k.lower() for k in kws_list}
        
        # ساخت فایل‌های زیرنویس
        stem = Path(norm_audio).stem
        ass_path, srt_path = self.subs.write(
            words=words,
            cfg=cfg.captions,
            kws=kws,
            ts_off=cfg.timestamp_offset,
            stem=stem,
            playresx=W,
            playresy=H,
        )
        
        return Path(ass_path), Path(srt_path), kws

    def _build_cta_enable(self, cta_cfg) -> str:
        """ساخت عبارت زمانی نمایش CTA (واضح‌تر)"""
        start = cta_cfg.start_s
        repeat = max(cta_cfg.repeat_s, 0.001)
        
        # نمایش تناوبی از زمان start
        # هر repeat ثانیه یکبار نمایش داده می‌شود
        return f"gte(t,{start})*not(mod(t-{start},{repeat}))"

    def _get_encoder_params(self) -> List[str]:
        """پارامترهای انکودر ویدئو (NVENC یا x264)"""
        if FFmpegCommander.has_nvenc():
            log.info("🚀 استفاده از NVENC (سخت‌افزاری)")
            return ["-c:v", "h264_nvenc", "-preset", "fast"]
        else:
            log.info("🐌 استفاده از libx264 (نرم‌افزاری)")
            return [
                "-c:v", "libx264", 
                "-preset", "veryfast", 
                "-crf", str(self.defaults.video_crf)
            ]

    def _copy_to_drive(self, out_path: Path, srt_path: Path):
        """کپی فایل‌ها به درایو خارجی (اگر موجود باشد)"""
        if not self.paths.out_drive:
            return
        
        try:
            shutil.copy2(str(out_path), str(self.paths.out_drive / out_path.name))
            shutil.copy2(str(srt_path), str(self.paths.out_drive / srt_path.name))
            log.info("✅ فایل‌ها به درایو کپی شدند")
        except Exception as e:
            log.warning(f"⚠️  کپی به درایو ناموفق: {e}")

    # ========== متد اصلی render ==========
    def render(self, cfg: ProjectCfg) -> Tuple[str, str, int, str]:
        """رندر ویدئوی نهایی"""
        W, H = cfg.visual.width, cfg.visual.height
        
        # 1️⃣ بررسی فایل‌ها
        audio_file = self.paths.assets / cfg.audio.filename
        bg_file = self.paths.assets / cfg.visual.bg_image
        
        if not bg_file.exists():
            raise FileNotFoundError(f"❌ تصویر پس‌زمینه پیدا نشد: {bg_file}")
        
        # 2️⃣ آماده‌سازی صدا
        norm_audio, main_dur = self._validate_audio(audio_file, cfg)
        
        # 3️⃣ مدیریت ورودی‌ها
        inputs = InputManager(self.paths, cfg)
        inputs.add_background(bg_file)
        inputs.add_audio(norm_audio)
        
        # فایل‌های اختیاری
        intro_path = (self.paths.assets / cfg.intro_outro.intro_mp4) if cfg.intro_outro.intro_mp4 else None
        outro_path = (self.paths.assets / cfg.intro_outro.outro_mp4) if cfg.intro_outro.outro_mp4 else None
        cta_path = (self.paths.assets / cfg.cta.loop_mp4) if cfg.cta.loop_mp4 else None
        
        inputs.add_optional("intro", intro_path)
        inputs.add_optional("outro", outro_path)
        inputs.add_optional("cta", cta_path)
        
        idx = inputs.get_index()
        
        # محاسبه مدت زمان کل
        intro_dur = FFmpegCommander.probe_duration(intro_path) if intro_path else 0.0
        outro_dur = FFmpegCommander.probe_duration(outro_path) if outro_path else 0.0
        total_dur = intro_dur + main_dur + outro_dur
        
        log.info(f"⏱️  مدت زمان: intro={intro_dur:.1f}s + main={main_dur:.1f}s + outro={outro_dur:.1f}s = {total_dur:.1f}s")
        
        # 4️⃣ زیرنویس
        ass_path, srt_path, kws = self._prepare_subtitles(norm_audio, cfg, W, H)
        
        # 5️⃣ ساخت فیلتر گراف
        fg = FilterGraphBuilder(W, H)
        
        # پس‌زمینه با Ken Burns
        kb_filter = self._build_ken_burns(W, H, total_dur, self.defaults.fps)
        fg.add_base(idx["bg"], f"{kb_filter},setpts=PTS-STARTPTS")
        
        # Intro
        if "intro" in idx and intro_dur > 0:
            fg.add_scaled_input(idx["intro"], "vintro")
            fg.overlay("vintro", f"between(t,0,{intro_dur})")
        
        # Outro
        if "outro" in idx and outro_dur > 0:
            start_o = total_dur - outro_dur
            fg.add_scaled_input(idx["outro"], "voutro")
            fg.overlay("voutro", f"between(t,{start_o},{total_dur})")
        
        # CTA
        if "cta" in idx and cfg.cta.loop_mp4:
            enable_cta = self._build_cta_enable(cfg.cta)
            fg.chromakey_overlay(
                idx["cta"],
                cfg.cta.key_color,
                cfg.cta.similarity,
                cfg.cta.blend,
                enable_cta
            )
        
        # زیرنویس
        if FFmpegCommander.has_libass() and ass_path.exists():
            font_dir = Path(FONTS)
            try:
                fontname = getattr(cfg.captions, "font_name", None) or pick_default_font_name(font_dir)
            except Exception:
                fontname = "DejaVu Sans"
            
            fonts_dir = build_fonts_only(font_dir, self.paths.tmp)
            margin_v = getattr(cfg.captions, "margin_v", 80)
            fg.burn_subtitles(ass_path, fonts_dir, fontname, margin_v)
        
        filter_graph = fg.finalize()
        
        # 6️⃣ مسیر خروجی
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{sanitize_filename(norm_audio.stem)}_{W}x{H}.mp4"
        out_path = self.paths.out_local / filename
        
        # 7️⃣ دستور FFmpeg
        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            *inputs.get_inputs(),
            "-filter_complex", filter_graph,
            "-map", "[vout]",
            "-map", f"{idx['audio']}:a",
            "-t", str(total_dur),
            *self._get_encoder_params(),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.defaults.audio_bitrate,
            str(out_path),
        ]
        
        log.info("🎬 شروع رندر...")
        sh(cmd, "Render FFmpeg")
        log.info(f"✅ ویدئو رندر شد: {out_path.name}")
        
        # 8️⃣ کپی به درایو
        self._copy_to_drive(out_path, srt_path)
        
        return (str(out_path), str(norm_audio), len(fg.filters), str(srt_path))