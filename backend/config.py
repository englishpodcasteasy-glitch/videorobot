# -*- coding: utf-8 -*-
"""
VideoRobot — Config (نسخه تمیز و کامل)

مدیریت تنظیمات پروژه:
- داده‌کلاس‌های تایپ‌شده با validation
- Enum های استاندارد
- I/O: JSON, YAML, Dict
- مدیریت مسیرها
"""
from __future__ import annotations

import enum
import json
import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, Any, Dict


# ===========================================================================
# SECTION 1: مدیریت مسیرها
# ===========================================================================

@dataclass(slots=True)
class Paths:
    """مسیرهای پروژه"""
    base_local: Path
    base_drive: Optional[Path]
    tmp: Path
    out_local: Path
    out_drive: Optional[Path]
    assets: Path
    figures: Path
    music: Path
    broll: Path
    
    def resolve_all(self) -> Paths:
        """تبدیل همه مسیرها به absolute و resolve شده"""
        def resolve_path(p: Optional[Path]) -> Optional[Path]:
            return None if p is None else p.expanduser().resolve()
        
        return Paths(
            base_local=resolve_path(self.base_local),
            base_drive=resolve_path(self.base_drive),
            tmp=resolve_path(self.tmp),
            out_local=resolve_path(self.out_local),
            out_drive=resolve_path(self.out_drive),
            assets=resolve_path(self.assets),
            figures=resolve_path(self.figures),
            music=resolve_path(self.music),
            broll=resolve_path(self.broll),
        )
    
    def ensure_dirs(self) -> None:
        """ایجاد تمام دایرکتوری‌های مورد نیاز"""
        required_dirs = [
            self.tmp,
            self.out_local,
            self.assets,
            self.figures,
            self.music,
            self.broll,
        ]
        
        for directory in required_dirs:
            directory.mkdir(parents=True, exist_ok=True)
        
        if self.out_drive:
            self.out_drive.mkdir(parents=True, exist_ok=True)
        
        if self.base_drive:
            self.base_drive.mkdir(parents=True, exist_ok=True)


# ===========================================================================
# SECTION 2: Enum های استاندارد
# ===========================================================================

class Aspect(enum.Enum):
    """نسبت تصویر ویدئو"""
    V9x16 = (9, 16)    # عمودی (Shorts, Reels)
    V1x1 = (1, 1)      # مربعی
    V16x9 = (16, 9)    # افقی (YouTube)
    
    @staticmethod
    def parse(val: Any) -> Aspect:
        """
        تبدیل مقدار به Aspect
        
        فرمت‌های پشتیبانی شده:
        - "9:16", "1:1", "16:9"
        - "9x16", "1x1", "16x9"
        - (9, 16), (1, 1), (16, 9)
        - Aspect enum
        """
        if isinstance(val, Aspect):
            return val
        
        # نرمال‌سازی رشته
        normalized = str(val).strip().lower()
        normalized = normalized.replace("v", "").replace("×", "x").replace(":", "x")
        
        # نگاشت رشته‌ها
        string_map = {
            "9x16": Aspect.V9x16,
            "1x1": Aspect.V1x1,
            "16x9": Aspect.V16x9,
        }
        
        if normalized in string_map:
            return string_map[normalized]
        
        # تلاش برای parse کردن به عنوان tuple
        if "x" in normalized:
            try:
                width, height = normalized.split("x", 1)
                pair = (int(width), int(height))
                
                tuple_map = {
                    (9, 16): Aspect.V9x16,
                    (1, 1): Aspect.V1x1,
                    (16, 9): Aspect.V16x9,
                }
                
                if pair in tuple_map:
                    return tuple_map[pair]
            except (ValueError, TypeError):
                pass
        
        raise ValueError(f"Aspect نامعتبر: {val!r}. باید 9:16, 1:1 یا 16:9 باشد")
    
    @property
    def width(self) -> int:
        """عرض بر اساس نسبت"""
        width_map = {
            Aspect.V9x16: 1080,
            Aspect.V1x1: 1080,
            Aspect.V16x9: 1920,
        }
        return width_map[self]
    
    @property
    def height(self) -> int:
        """ارتفاع بر اساس نسبت"""
        height_map = {
            Aspect.V9x16: 1920,
            Aspect.V1x1: 1080,
            Aspect.V16x9: 1080,
        }
        return height_map[self]


class CaptionPosition(enum.Enum):
    """موقعیت زیرنویس"""
    TOP = "Top"
    MIDDLE = "Middle"
    BOTTOM = "Bottom"
    
    @staticmethod
    def parse(val: Any) -> CaptionPosition:
        """تبدیل به CaptionPosition"""
        if isinstance(val, CaptionPosition):
            return val
        
        normalized = str(val).strip().lower()
        
        position_map = {
            "top": CaptionPosition.TOP,
            "middle": CaptionPosition.MIDDLE,
            "center": CaptionPosition.MIDDLE,
            "bottom": CaptionPosition.BOTTOM,
        }
        
        if normalized in position_map:
            return position_map[normalized]
        
        raise ValueError(f"موقعیت نامعتبر: {val!r}. باید Top, Middle یا Bottom باشد")


class ShortsMode(enum.Enum):
    """حالت تولید Shorts"""
    OFF = "Off"      # غیرفعال
    AUTO = "Auto"    # خودکار
    FORCE = "Force"  # اجباری
    
    @staticmethod
    def parse(val: Any) -> ShortsMode:
        """تبدیل به ShortsMode"""
        if isinstance(val, ShortsMode):
            return val
        
        normalized = str(val).strip().lower()
        
        mode_map = {
            "off": ShortsMode.OFF,
            "auto": ShortsMode.AUTO,
            "force": ShortsMode.FORCE,
        }
        
        if normalized in mode_map:
            return mode_map[normalized]
        
        raise ValueError(f"حالت نامعتبر: {val!r}. باید Off, Auto یا Force باشد")


# ===========================================================================
# SECTION 3: توابع Validation
# ===========================================================================

_HEX_COLOR_PATTERN = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _ensure_hex_color(color: str) -> str:
    """اطمینان از فرمت صحیح رنگ hex"""
    if not isinstance(color, str) or not _HEX_COLOR_PATTERN.match(color or ""):
        raise ValueError(f"رنگ نامعتبر (فرمت: #RRGGBB): {color!r}")
    
    return color if color.startswith("#") else f"#{color}"


def _validate_float_range(name: str, value: float, min_val: float, max_val: float) -> float:
    """اعتبارسنجی محدوده عددی float"""
    try:
        num = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} باید عدد باشد")
    
    if not (min_val <= num <= max_val):
        raise ValueError(f"{name} خارج از محدوده [{min_val}, {max_val}]: {value}")
    
    return num


def _validate_int_range(name: str, value: int, min_val: int, max_val: int) -> int:
    """اعتبارسنجی محدوده عددی int"""
    try:
        num = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} باید عدد صحیح باشد")
    
    if not (min_val <= num <= max_val):
        raise ValueError(f"{name} خارج از محدوده [{min_val}, {max_val}]: {value}")
    
    return num


# ===========================================================================
# SECTION 4: داده‌کلاس‌های تنظیمات
# ===========================================================================

@dataclass(slots=True)
class AudioCfg:
    """تنظیمات صوت"""
    filename: str
    whisper_model: str = "medium"
    use_vad: bool = True
    target_lufs: float = -16.0   # [-36, -6]
    target_lra: float = 11.0     # [1, 20]
    target_tp: float = -2.0      # [-6, -0.1]
    
    def validate(self) -> AudioCfg:
        """اعتبارسنجی تنظیمات صوت"""
        _validate_float_range("audio.target_lufs", self.target_lufs, -36.0, -6.0)
        _validate_float_range("audio.target_lra", self.target_lra, 1.0, 20.0)
        _validate_float_range("audio.target_tp", self.target_tp, -6.0, -0.1)
        
        if not str(self.filename or "").strip():
            raise ValueError("audio.filename الزامی است")
        
        return self


@dataclass(slots=True)
class CaptionCfg:
    """تنظیمات زیرنویس"""
    font_choice: Optional[str]
    font_name: Optional[str]
    font_size: int
    active_color: str
    keyword_color: str
    border_thickness: int
    max_words_per_line: int
    max_words_per_caption: int
    position: CaptionPosition
    margin_v: int
    
    def validate(self) -> CaptionCfg:
        """اعتبارسنجی تنظیمات زیرنویس"""
        _validate_int_range("captions.font_size", self.font_size, 12, 150)
        _validate_int_range("captions.border_thickness", self.border_thickness, 0, 12)
        _validate_int_range("captions.max_words_per_line", self.max_words_per_line, 1, 20)
        _validate_int_range("captions.max_words_per_caption", self.max_words_per_caption, 1, 50)
        _validate_int_range("captions.margin_v", self.margin_v, 0, 300)
        
        self.active_color = _ensure_hex_color(self.active_color)
        self.keyword_color = _ensure_hex_color(self.keyword_color)
        self.position = CaptionPosition.parse(self.position)
        
        return self


@dataclass(slots=True)
class FigureCfg:
    """تنظیمات Figure"""
    use: bool
    duration_s: float
    
    def validate(self) -> FigureCfg:
        """اعتبارسنجی تنظیمات Figure"""
        _validate_float_range("figures.duration_s", self.duration_s, 0.1, 600.0)
        return self


@dataclass(slots=True)
class IntroOutroCfg:
    """تنظیمات Intro و Outro"""
    intro_mp4: Optional[str]
    intro_key: bool
    outro_mp4: Optional[str]
    outro_key: bool


@dataclass(slots=True)
class CTACfg:
    """تنظیمات Call-to-Action"""
    loop_mp4: Optional[str]
    start_s: float
    repeat_s: float
    key_color: str
    similarity: float
    blend: float
    position: CaptionPosition
    
    def validate(self) -> CTACfg:
        """اعتبارسنجی تنظیمات CTA"""
        _validate_float_range("cta.start_s", self.start_s, 0.0, 36000.0)
        _validate_float_range("cta.repeat_s", self.repeat_s, 0.01, 36000.0)
        _validate_float_range("cta.similarity", self.similarity, 0.0, 1.0)
        _validate_float_range("cta.blend", self.blend, 0.0, 1.0)
        
        self.key_color = _ensure_hex_color(self.key_color)
        self.position = CaptionPosition.parse(self.position)
        
        return self


@dataclass(slots=True)
class BGMCfg:
    """تنظیمات موسیقی پس‌زمینه"""
    name: Optional[str]
    gain_db: float
    auto_duck: bool
    duck_threshold: float
    duck_ratio: float
    duck_attack: int
    duck_release: int
    
    def validate(self) -> BGMCfg:
        """اعتبارسنجی تنظیمات BGM"""
        _validate_float_range("bgm.gain_db", self.gain_db, -60.0, 12.0)
        _validate_float_range("bgm.duck_threshold", self.duck_threshold, -60.0, 0.0)
        _validate_float_range("bgm.duck_ratio", self.duck_ratio, 1.0, 30.0)
        _validate_int_range("bgm.duck_attack", self.duck_attack, 1, 20000)
        _validate_int_range("bgm.duck_release", self.duck_release, 1, 60000)
        
        return self


@dataclass(slots=True)
class BrollCfg:
    """تنظیمات B-roll"""
    use: bool
    first_at: float
    every_s: float
    duration_s: float
    
    def validate(self) -> BrollCfg:
        """اعتبارسنجی تنظیمات B-roll"""
        _validate_float_range("broll.first_at", self.first_at, 0.0, 36000.0)
        _validate_float_range("broll.every_s", self.every_s, 0.1, 36000.0)
        _validate_float_range("broll.duration_s", self.duration_s, 0.1, 36000.0)
        
        return self


@dataclass(slots=True)
class VisualCfg:
    """تنظیمات بصری"""
    bg_image: str
    aspect: Aspect
    ken_burns: bool
    
    @property
    def width(self) -> int:
        """عرض ویدئو"""
        return self.aspect.width
    
    @property
    def height(self) -> int:
        """ارتفاع ویدئو"""
        return self.aspect.height
    
    def validate(self) -> VisualCfg:
        """اعتبارسنجی تنظیمات بصری"""
        self.aspect = Aspect.parse(self.aspect)
        
        if not str(self.bg_image or "").strip():
            raise ValueError("visual.bg_image الزامی است")
        
        return self


@dataclass(slots=True)
class ShortsCfg:
    """تنظیمات Shorts"""
    mode: ShortsMode
    min_s: int
    max_s: int
    
    def validate(self) -> ShortsCfg:
        """اعتبارسنجی تنظیمات Shorts"""
        self.mode = ShortsMode.parse(self.mode)
        _validate_int_range("shorts.min_s", self.min_s, 5, 300)
        _validate_int_range("shorts.max_s", self.max_s, 5, 600)
        
        if self.min_s > self.max_s:
            raise ValueError("shorts.min_s نمی‌تواند بزرگتر از shorts.max_s باشد")
        
        return self


# ===========================================================================
# SECTION 5: کلاس اصلی Config
# ===========================================================================

@dataclass(slots=True)
class ProjectCfg:
    """تنظیمات کامل پروژه"""
    audio: AudioCfg
    captions: CaptionCfg
    figures: FigureCfg
    intro_outro: IntroOutroCfg
    cta: CTACfg
    bgm: BGMCfg
    broll: BrollCfg
    visual: VisualCfg
    shorts: ShortsCfg
    dry_run: bool
    timestamp_offset: float = 0.0
    paths: Optional[Paths] = field(default=None)
    
    def validate(self) -> ProjectCfg:
        """اعتبارسنجی کامل تنظیمات"""
        self.audio.validate()
        self.captions.validate()
        self.figures.validate()
        self.cta.validate()
        self.bgm.validate()
        self.broll.validate()
        self.visual.validate()
        self.shorts.validate()
        
        _validate_float_range("timestamp_offset", self.timestamp_offset, -36000.0, 36000.0)
        
        if self.paths:
            self.paths = self.paths.resolve_all()
        
        return self
    
    # -----------------------------------------------------------------------
    # I/O Methods
    # -----------------------------------------------------------------------
    
    def to_dict(self) -> Dict[str, Any]:
        """تبدیل به Dictionary"""
        data = asdict(self)
        
        def fix_value(obj: Any) -> Any:
            """تبدیل انواع خاص به مقادیر قابل سریالیزه"""
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, enum.Enum):
                return obj.value
            return obj
        
        def walk_dict(x: Any) -> Any:
            """پیمایش بازگشتی ساختار"""
            if isinstance(x, dict):
                return {k: walk_dict(fix_value(v)) for k, v in x.items()}
            if isinstance(x, list):
                return [walk_dict(fix_value(v)) for v in x]
            return fix_value(x)
        
        result = walk_dict(data)
        
        # تبدیل Aspect به فرمت خوانا
        if "visual" in result and isinstance(self.visual.aspect, Aspect):
            aspect_map = {
                Aspect.V9x16: "9:16",
                Aspect.V1x1: "1:1",
                Aspect.V16x9: "16:9",
            }
            result["visual"]["aspect"] = aspect_map[self.visual.aspect]
        
        return result
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> ProjectCfg:
        """ساخت از Dictionary"""
        visual_data = data.get("visual", {})
        shorts_data = data.get("shorts", {})
        
        config = ProjectCfg(
            audio=AudioCfg(**data["audio"]),
            captions=CaptionCfg(**data["captions"]),
            figures=FigureCfg(**data["figures"]),
            intro_outro=IntroOutroCfg(**data["intro_outro"]),
            cta=CTACfg(**data["cta"]),
            bgm=BGMCfg(**data["bgm"]),
            broll=BrollCfg(**data["broll"]),
            visual=VisualCfg(
                bg_image=visual_data["bg_image"],
                aspect=Aspect.parse(visual_data.get("aspect", "16:9")),
                ken_burns=bool(visual_data.get("ken_burns", False)),
            ),
            shorts=ShortsCfg(
                mode=ShortsMode.parse(shorts_data.get("mode", "Off")),
                min_s=int(shorts_data.get("min_s", 45)),
                max_s=int(shorts_data.get("max_s", 90)),
            ),
            dry_run=bool(data.get("dry_run", False)),
            timestamp_offset=float(data.get("timestamp_offset", 0.0)),
            paths=Paths(**data["paths"]).resolve_all() if data.get("paths") else None,
        )
        
        return config.validate()
    
    @staticmethod
    def from_json(text: str) -> ProjectCfg:
        """بارگذاری از JSON"""
        return ProjectCfg.from_dict(json.loads(text))
    
    @staticmethod
    def from_yaml(text: str) -> ProjectCfg:
        """بارگذاری از YAML"""
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "PyYAML نصب نیست. برای خواندن YAML نصب کنید: pip install pyyaml"
            ) from e
        
        return ProjectCfg.from_dict(yaml.safe_load(text))
    
    def to_json(self, indent: int = 2) -> str:
        """تبدیل به JSON"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    @staticmethod
    def load_from_file(path: Path) -> ProjectCfg:
        """بارگذاری از فایل (تشخیص خودکار فرمت)"""
        content = path.read_text(encoding="utf-8")
        
        if path.suffix.lower() in (".yaml", ".yml"):
            return ProjectCfg.from_yaml(content)
        elif path.suffix.lower() == ".json":
            return ProjectCfg.from_json(content)
        else:
            raise ValueError(f"فرمت فایل پشتیبانی نمی‌شود: {path.suffix}")
    
    def save_to_file(self, path: Path) -> None:
        """ذخیره در فایل"""
        if path.suffix.lower() == ".json":
            path.write_text(self.to_json(), encoding="utf-8")
        elif path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
                path.write_text(
                    yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False),
                    encoding="utf-8"
                )
            except ImportError:
                raise RuntimeError("PyYAML نصب نیست")
        else:
            raise ValueError(f"فرمت فایل پشتیبانی نمی‌شود: {path.suffix}")


# ===========================================================================
# SECTION 6: ثابت‌های عمومی
# ===========================================================================

FONTS = Path(os.getenv("VR_FONTS_DIR", "Assets/Fonts")).expanduser()


# ===========================================================================
# پایان فایل
# ===========================================================================