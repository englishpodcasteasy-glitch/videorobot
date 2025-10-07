# -*- coding: utf-8 -*-
"""
VideoRobot — Scheduler (نسخه تمیز و کامل)

مدیریت هوشمند:
- رونویسی صوت با Faster-Whisper + cache مدل‌ها
- استخراج کلمات کلیدی با YAKE
- انتخاب بهترین بازه برای Shorts
- زمان‌بندی Figure و B-roll
"""
from __future__ import annotations

import logging
import math
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

from .utils import ensure_pkg_safe

log = logging.getLogger("VideoRobot.scheduler")


# ===========================================================================
# SECTION 1: نصب و import وابستگی‌ها
# ===========================================================================

# نصب خودکار پکیج‌ها در صورت عدم وجود
ensure_pkg_safe("yake", "yake==0.4.8")
ensure_pkg_safe("faster_whisper", "faster-whisper==1.0.3")
ensure_pkg_safe("ctranslate2", "ctranslate2==4.5.0")

from faster_whisper import WhisperModel  # type: ignore
import yake  # type: ignore


# ===========================================================================
# SECTION 2: تشخیص سخت‌افزار و تنظیمات Runtime
# ===========================================================================

@dataclass(frozen=True)
class ASRRuntime:
    """تنظیمات اجرای Faster-Whisper"""
    device: str          # "cuda" یا "cpu"
    compute_type: str    # "int8_float16" (CUDA) یا "int8" (CPU)


def _detect_runtime(
    override_device: Optional[str] = None,
    override_compute: Optional[str] = None
) -> ASRRuntime:
    """
    تشخیص خودکار بهترین تنظیمات اجرا
    
    اولویت‌ها:
    1. پارامترهای تابع
    2. متغیرهای محیطی (VR_ASR_DEVICE, VR_ASR_COMPUTE)
    3. تشخیص خودکار
    
    پیش‌فرض:
    - CUDA موجود: device=cuda, compute_type=int8_float16
    - فقط CPU: device=cpu, compute_type=int8
    """
    device = override_device or os.getenv("VR_ASR_DEVICE")
    compute = override_compute or os.getenv("VR_ASR_COMPUTE")
    
    # تشخیص دستگاه
    if not device:
        try:
            import torch  # type: ignore
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    
    # انتخاب compute type بر اساس دستگاه
    if not compute:
        compute = "int8_float16" if device == "cuda" else "int8"
    
    return ASRRuntime(device=device, compute_type=compute)


# ===========================================================================
# SECTION 3: Cache مدل‌های Whisper با LRU
# ===========================================================================

class _ModelCache:
    """
    Cache با الگوریتم LRU برای مدل‌های Whisper
    
    ویژگی‌ها:
    - نگهداری تعداد محدود مدل در حافظه
    - آزادسازی خودکار مدل‌های قدیمی
    - Thread-safe
    """
    
    def __init__(self, capacity: int = 2) -> None:
        """
        Args:
            capacity: حداکثر تعداد مدل‌های نگهداری شده
        """
        self.capacity = max(1, capacity)
        self._lock = threading.RLock()
        self._store: OrderedDict[Tuple[str, str, str], WhisperModel] = OrderedDict()
    
    def get(self, key: Tuple[str, str, str]) -> Optional[WhisperModel]:
        """دریافت مدل از cache (اگر موجود باشد)"""
        with self._lock:
            model = self._store.get(key)
            if model is not None:
                # انتقال به انتهای صف (most recently used)
                self._store.move_to_end(key)
            return model
    
    def put(self, key: Tuple[str, str, str], model: WhisperModel) -> None:
        """افزودن مدل به cache"""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                return
            
            self._store[key] = model
            
            # اگر ظرفیت پر شد، قدیمی‌ترین را حذف کن
            if len(self._store) > self.capacity:
                old_key, old_model = self._store.popitem(last=False)
                self._unload_model(old_model)
    
    def pop(self, key: Tuple[str, str, str]) -> None:
        """حذف یک مدل خاص از cache"""
        with self._lock:
            model = self._store.pop(key, None)
            if model:
                self._unload_model(model)
    
    def clear(self) -> None:
        """پاک کردن تمام cache"""
        with self._lock:
            for model in self._store.values():
                self._unload_model(model)
            self._store.clear()
    
    @staticmethod
    def _unload_model(model: WhisperModel) -> None:
        """آزادسازی حافظه مدل"""
        try:
            # جستجوی متد unload_model
            unload = getattr(model, "unload_model", None)
            if not unload:
                unload = getattr(getattr(model, "model", None), "unload_model", None)
            
            if callable(unload):
                unload()
        except Exception as e:
            log.debug("خطا در unload مدل: %s", e)


# ===========================================================================
# SECTION 4: کلاس اصلی Scheduler
# ===========================================================================

class Scheduler:
    """
    مدیر اصلی برای:
    - رونویسی صوت با Whisper
    - استخراج کلمات کلیدی
    - انتخاب بازه Shorts
    - زمان‌بندی Figure و B-roll
    """
    
    # Cache مشترک برای همه instance ها
    _CACHE = _ModelCache(capacity=int(os.getenv("VR_ASR_CACHE_CAP", "2")))
    _LOCK = threading.RLock()
    
    def __init__(
        self,
        device: Optional[str] = None,
        compute_type: Optional[str] = None
    ) -> None:
        """
        Args:
            device: "cuda" یا "cpu" (None = تشخیص خودکار)
            compute_type: نوع محاسبه (None = تشخیص خودکار)
        """
        runtime = _detect_runtime(device, compute_type)
        self._device = runtime.device
        self._compute_type = runtime.compute_type
        
        log.info(
            "Scheduler آماده شد: device=%s, compute_type=%s",
            self._device, self._compute_type
        )
    
    # -----------------------------------------------------------------------
    # مدیریت مدل‌ها
    # -----------------------------------------------------------------------
    
    def _get_model(self, size: str) -> WhisperModel:
        """
        دریافت یا بارگذاری مدل Whisper
        
        Args:
            size: اندازه مدل (tiny, base, small, medium, large)
        
        Returns:
            مدل آماده برای رونویسی
        """
        key = (str(size), self._device, self._compute_type)
        
        # بررسی cache
        model = self._CACHE.get(key)
        if model is not None:
            return model
        
        # بارگذاری مدل جدید (thread-safe)
        with self._LOCK:
            # بررسی مجدد (ممکن است در همین لحظه بارگذاری شده باشد)
            model = self._CACHE.get(key)
            if model is not None:
                return model
            
            log.info(
                "بارگذاری مدل Whisper: size=%s, device=%s, compute=%s",
                size, self._device, self._compute_type
            )
            
            try:
                model = WhisperModel(
                    str(size),
                    device=self._device,
                    compute_type=self._compute_type
                )
            except Exception as e:
                log.error("خطا در بارگذاری مدل '%s': %s", size, e)
                raise RuntimeError(
                    f"بارگذاری مدل Whisper ناموفق بود: {size} "
                    f"({self._device}/{self._compute_type})"
                ) from e
            
            self._CACHE.put(key, model)
            log.info("مدل آماده است")
            return model
    
    def close(self, size: str) -> None:
        """آزادسازی یک مدل خاص"""
        key = (str(size), self._device, self._compute_type)
        self._CACHE.pop(key)
    
    @staticmethod
    def close_all() -> None:
        """آزادسازی تمام مدل‌های cache شده"""
        Scheduler._CACHE.clear()
    
    # -----------------------------------------------------------------------
    # رونویسی صوت
    # -----------------------------------------------------------------------
    
    def transcribe_words(
        self,
        audio_path: str | Path,
        size: str,
        use_vad: bool,
        *,
        language: Optional[str] = None,
        beam_size: int = 5,
        temperature: float = 0.0,
        chunk_length: int = 30,
        vad_parameters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        رونویسی صوت با زمان‌بندی کلمه‌ای
        
        Args:
            audio_path: مسیر فایل صوتی
            size: اندازه مدل Whisper
            use_vad: فعال‌سازی Voice Activity Detection
            language: زبان (None = تشخیص خودکار)
            beam_size: اندازه beam search
            temperature: دمای sampling
            chunk_length: طول هر chunk (ثانیه)
            vad_parameters: پارامترهای اضافی VAD
        
        Returns:
            لیست کلمات: [{"s": start, "e": end, "raw": text}, ...]
        """
        audio_file = Path(str(audio_path))
        if not audio_file.exists():
            raise FileNotFoundError(f"فایل صوتی پیدا نشد: {audio_file}")
        
        # تنظیمات VAD
        vad_params = {}
        if use_vad:
            vad_params = {
                "min_silence_duration_ms": 2000,
                "speech_pad_ms": 200
            }
            if vad_parameters:
                vad_params.update(vad_parameters)
        
        # دریافت مدل
        model = self._get_model(str(size))
        
        # رونویسی
        try:
            segments, _info = model.transcribe(
                str(audio_file),
                language=language,
                beam_size=int(beam_size),
                temperature=float(temperature),
                vad_filter=bool(use_vad),
                vad_parameters=vad_params,
                word_timestamps=True,
                chunk_length=max(1, int(chunk_length)),
            )
        except Exception as e:
            log.error("خطا در رونویسی: %s", e, exc_info=True)
            raise RuntimeError(f"رونویسی ناموفق بود: {e}") from e
        
        # استخراج کلمات
        words: List[Dict[str, Any]] = []
        for segment in segments:
            word_list = getattr(segment, "words", None) or []
            for word_obj in word_list:
                text = (getattr(word_obj, "word", "") or "").strip()
                if not text:
                    continue
                
                start = float(getattr(word_obj, "start", 0.0) or 0.0)
                end = float(getattr(word_obj, "end", 0.0) or 0.0)
                
                # بررسی اعتبار زمان‌ها
                if any([
                    math.isnan(start), math.isinf(start),
                    math.isnan(end), math.isinf(end),
                    end < start
                ]):
                    continue
                
                words.append({
                    "s": max(0.0, start),
                    "e": max(0.0, end),
                    "raw": text
                })
        
        log.info("رونویسی تکمیل شد: %d کلمه", len(words))
        return words
    
    # -----------------------------------------------------------------------
    # استخراج کلمات کلیدی
    # -----------------------------------------------------------------------
    
    @staticmethod
    def extract_keywords(
        text: str,
        topk: int = 12,
        *,
        ngram_max: int = 1,
        dedup_lim: float = 0.9,
        min_token_len: int = 2,
    ) -> List[str]:
        """
        استخراج کلمات کلیدی با YAKE
        
        Args:
            text: متن ورودی
            topk: تعداد کلمات کلیدی
            ngram_max: حداکثر طول n-gram
            dedup_lim: محدودیت تکراری (0-1)
            min_token_len: حداقل طول توکن
        
        Returns:
            لیست کلمات کلیدی
        """
        # پاکسازی متن
        tokens = [
            token for token in (text or "").split()
            if len(token) >= min_token_len
        ]
        normalized = " ".join(tokens)
        
        # بررسی طول متن
        if len(normalized) < 8:
            log.debug("متن برای استخراج keyword خیلی کوتاه است")
            return []
        
        try:
            extractor = yake.KeywordExtractor(
                n=int(ngram_max),
                dedupLim=float(dedup_lim),
                top=int(topk)
            )
            
            keywords = [word for word, _score in extractor.extract_keywords(normalized)]
            
            # حذف تکراری با حفظ ترتیب
            seen = set()
            unique_keywords: List[str] = []
            
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower not in seen:
                    seen.add(keyword_lower)
                    unique_keywords.append(keyword)
            
            log.debug("استخراج شد: %d keyword", len(unique_keywords))
            return unique_keywords
            
        except Exception as e:
            log.warning("خطا در استخراج keywords: %s", e)
            return []
    
    # -----------------------------------------------------------------------
    # انتخاب بازه Shorts
    # -----------------------------------------------------------------------
    
    @dataclass(frozen=True)
    class ShortsWeights:
        """وزن‌های امتیازدهی برای انتخاب بازه Shorts"""
        step: float = 5.0          # گام جستجو (ثانیه)
        w_keywords: float = 1.4    # وزن تراکم keywords
        w_rate: float = 0.25       # وزن سرعت گفتار
        w_len: float = 0.35        # وزن طول مناسب
    
    def select_shorts_window(
        self,
        words: List[Dict[str, Any]],
        tmin: float,
        tmax: float,
        whole: float,
        *,
        weights: Optional[ShortsWeights] = None,
    ) -> Tuple[float, float]:
        """
        انتخاب بهترین بازه زمانی برای Shorts
        
        معیارهای امتیازدهی:
        - تراکم کلمات کلیدی
        - سرعت مناسب گفتار
        - نزدیکی به طول هدف
        - عدم سکوت طولانی
        
        Args:
            words: لیست کلمات رونویسی شده
            tmin: حداقل طول (ثانیه)
            tmax: حداکثر طول (ثانیه)
            whole: کل طول صوت (ثانیه)
            weights: وزن‌های امتیازدهی
        
        Returns:
            (start, end) بهترین بازه
        """
        # مدیریت حالت خالی
        if not words:
            return 0.0, min(max(0.1, tmax), whole)
        
        # اصلاح ورودی‌های نامعتبر
        if tmin > tmax:
            tmin, tmax = tmax, tmin
        
        weights = weights or self.ShortsWeights()
        
        # استخراج کلمات کلیدی
        full_text = " ".join(word["raw"] for word in words)
        keywords = {kw.lower() for kw in self.extract_keywords(full_text, 16)}
        
        # محدودیت افق جستجو
        last_word_time = words[-1]["e"] if words else 0.0
        horizon = min(last_word_time + 2.0, whole)
        
        def calculate_score(start: float, end: float) -> float:
            """محاسبه امتیاز یک بازه"""
            # کلمات داخل بازه
            window_words = [
                w for w in words
                if (start <= w["s"] <= end) or (start <= w["e"] <= end)
            ]
            
            if not window_words:
                return -1.0
            
            duration = max(0.1, end - start)
            
            # 1. تراکم keywords
            keyword_count = sum(
                1 for w in window_words
                if w["raw"].lower() in keywords
            )
            density = keyword_count / max(1, len(window_words))
            
            # 2. سرعت گفتار (کلمه در ثانیه)
            rate = len(window_words) / duration
            
            # 3. جریمه سکوت
            total_silence = 0.0
            for i in range(1, len(window_words)):
                gap = max(0.0, window_words[i]["s"] - window_words[i-1]["e"])
                total_silence += gap
            silence_penalty = min(1.0, total_silence / duration) * 0.5
            
            # 4. ترجیح طول (نزدیک به میانه بهتر است)
            target_length = 0.5 * (tmin + tmax)
            length_range = max(1e-6, (tmax - tmin) / 2.0)
            length_pref = max(0.0, 1.0 - abs(duration - target_length) / length_range)
            
            # محاسبه امتیاز نهایی
            score = (
                density * weights.w_keywords +
                rate * weights.w_rate +
                length_pref * weights.w_len -
                silence_penalty
            )
            
            return score
        
        # جستجوی بازه‌های مختلف
        candidates: List[Tuple[float, float, float]] = []  # (score, start, end)
        
        start_pos = 0.0
        while start_pos < max(0.0, horizon - tmin):
            # امتحان طول‌های مختلف
            for length in (tmin, 0.5 * (tmin + tmax), tmax):
                end_pos = min(start_pos + length, horizon)
                score = calculate_score(start_pos, end_pos)
                candidates.append((score, start_pos, end_pos))
            
            start_pos += weights.step
        
        # اگر هیچ کاندید معتبری نبود
        if not candidates:
            return 0.0, min(whole, tmax)
        
        # انتخاب بهترین
        best_score, best_start, best_end = max(candidates, key=lambda x: x[0])
        
        # اگر همه امتیازها منفی بودند، بازه پیش‌فرض
        if best_score < 0:
            return 0.0, min(whole, tmax)
        
        return round(best_start, 3), round(best_end, 3)
    
    # -----------------------------------------------------------------------
    # زمان‌بندی Figure و B-roll
    # -----------------------------------------------------------------------
    
    @staticmethod
    def schedule_figures(
        total_dur: float,
        use: bool,
        duration_s: float,
        n_figures: int
    ) -> List[Tuple[float, float, int]]:
        """
        توزیع یکنواخت Figure ها در طول ویدئو
        
        Args:
            total_dur: کل مدت ویدئو (ثانیه)
            use: فعال/غیرفعال
            duration_s: مدت نمایش هر figure
            n_figures: تعداد figure های موجود
        
        Returns:
            لیست: [(start, end, figure_index), ...]
        """
        if not use or n_figures <= 0 or total_dur <= 0.1 or duration_s <= 0.05:
            return []
        
        # محاسبه تعداد اسلات (3 تا 7 بسته به طول ویدئو)
        min_gap = max(6.0, duration_s * 2.0)
        num_slots = max(1, min(7, int(total_dur // min_gap)))
        
        # فاصله بین اسلات
        gap = max(duration_s, total_dur / (num_slots + 1))
        
        schedule: List[Tuple[float, float, int]] = []
        current_time = gap * 0.5
        
        for i in range(num_slots):
            start = min(max(0.0, current_time), max(0.0, total_dur - duration_s))
            end = min(total_dur, start + duration_s)
            figure_index = i % n_figures
            
            schedule.append((round(start, 3), round(end, 3), figure_index))
            current_time += gap
        
        log.debug("زمان‌بندی Figure: %d اسلات", len(schedule))
        return schedule
    
    @staticmethod
    def schedule_broll(
        total_dur: float,
        use: bool,
        first_at: float,
        every_s: float,
        duration_s: float
    ) -> List[Tuple[float, float]]:
        """
        تولید سری از بازه‌های B-roll
        
        Args:
            total_dur: کل مدت ویدئو (ثانیه)
            use: فعال/غیرفعال
            first_at: زمان شروع اولین B-roll
            every_s: فاصله بین B-roll ها (0 = فقط یکبار)
            duration_s: مدت هر B-roll
        
        Returns:
            لیست: [(start, end), ...]
        """
        if not use or total_dur <= 0.1 or duration_s <= 0.05:
            return []
        
        start_time = max(0.0, first_at)
        step = max(duration_s + 0.1, every_s) if every_s > 0 else math.inf
        
        schedule: List[Tuple[float, float]] = []
        
        while start_time < total_dur - 0.25 and len(schedule) < 100:
            end_time = min(total_dur, start_time + duration_s)
            schedule.append((round(start_time, 3), round(end_time, 3)))
            
            if not math.isfinite(step):
                break
            
            start_time += step
        
        log.debug("زمان‌بندی B-roll: %d بازه", len(schedule))
        return schedule


# ===========================================================================
# پایان فایل
# ===========================================================================