#!/usr/bin/env python3
"""Colab helper script that reproduces the one-click "God Mode v27-PRO" UI.

This variant emphasises production-minded defaults for Colab as well as
self-hosted runs.  Environment bootstrapping is idempotent, project roots are
configurable, and heavy dependencies load lazily.  The rendering pipeline now
performs structured validation of media inputs and constrains Whisper model
usage to avoid exhausting GPU memory during long-lived notebook sessions.
"""

from __future__ import annotations

import datetime
import functools
import gc
import hashlib
import logging
import os
import shlex
import subprocess
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    Iterator,
    List,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
)

if TYPE_CHECKING:  # pragma: no cover - imported dynamically at runtime
    import gradio as gr

LOGGER = logging.getLogger("god-mode")


def _setup_logging() -> None:
    """Install a simple stdout logger suitable for Colab notebooks."""

    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(asctime)s %(message)s", "%H:%M:%S")
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


_setup_logging()


def run_cmd(
    cmd: Sequence[str] | str,
    *,
    check: bool = True,
    text: bool = True,
    capture: bool = True,
    env: Optional[MutableMapping[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, raising detailed diagnostics on failure."""

    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    LOGGER.debug("$ %s", " ".join(cmd))
    proc = subprocess.run(
        list(cmd),
        stdout=(subprocess.PIPE if capture else None),
        stderr=(subprocess.PIPE if capture else None),
        text=text,
        env=env,
    )
    if check and proc.returncode != 0:
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        LOGGER.error("Command failed: %s\nSTDOUT: %s\nSTDERR: %s", cmd, stdout, stderr)
        raise RuntimeError(stderr if capture else "Command failed")
    return proc


def _iter_missing_imports(requirements: Iterable[Tuple[str, str]]) -> Iterator[str]:
    """Yield pip specifiers for packages that are not currently importable."""

    for spec, module in requirements:
        try:
            __import__(module)
        except Exception:
            yield spec


def ensure_pip_packages() -> None:
    """Install the runtime pip dependencies if they are not already present."""

    requirements: Tuple[Tuple[str, str], ...] = (
        ("gradio==5.49.0", "gradio"),
        ("faster-whisper==1.0.3", "faster_whisper"),
        ("Pillow>=10.4.0", "PIL"),
        ("fonttools>=4.54.1", "fontTools"),
    )
    missing = tuple(_iter_missing_imports(requirements))
    if missing:
        LOGGER.info("Installing pip packages: %s", ", ".join(missing))
        run_cmd(["pip", "install", "-q", "-U", *missing], check=True, capture=False)
    else:
        LOGGER.info("Pip packages already satisfied")

    target_torch = os.environ.get("GOD_MODE_TORCH_WHL")
    if target_torch:
        LOGGER.info("Installing Torch from GOD_MODE_TORCH_WHL override")
        run_cmd(["pip", "install", "-q", "-U", *shlex.split(target_torch)], capture=False)
        return

    try:
        import torch  # type: ignore

        desired = "2.1.2"
        if torch.__version__.startswith(desired):
            return
        LOGGER.info(
            "Torch version %s found – reinstalling target %s build",
            torch.__version__,
            desired,
        )
    except Exception:
        LOGGER.info("Torch not present – installing target build")

    run_cmd(
        [
            "pip",
            "install",
            "-q",
            "-U",
            "torch==2.1.2+cu121",
            "torchaudio==2.1.2+cu121",
            "--index-url",
            "https://download.pytorch.org/whl/cu121",
        ],
        check=True,
        capture=False,
    )


def ensure_apt_packages() -> None:
    """Install Ubuntu packages only when missing to avoid redundant work."""

    packages = ("ffmpeg", "libass9", "fontconfig", "fonts-dejavu-core")
    missing: List[str] = []
    for pkg in packages:
        result = run_cmd(["dpkg", "-s", pkg], check=False)
        if result.returncode != 0:
            missing.append(pkg)
    if not missing:
        LOGGER.info("APT packages already installed")
        return

    LOGGER.info("Installing APT packages: %s", ", ".join(missing))
    run_cmd("apt-get -y update -qq", check=True, capture=False)
    run_cmd(
        ["apt-get", "-y", "install", "-qq", *missing],
        check=True,
        capture=False,
    )


def ensure_environment() -> None:
    """Perform one-time environment preparation."""

    if os.environ.get("GOD_MODE_SKIP_SETUP") == "1":
        LOGGER.info("GOD_MODE_SKIP_SETUP=1 – skipping dependency installation")
        return
    ensure_pip_packages()
    ensure_apt_packages()


GRADIO = None
TORCH = None
WHISPER_MODEL_CLASS = None
TTFONT_CLASS = None


def load_dependencies() -> None:
    """Import heavy dependencies lazily once the environment is ready."""

    global GRADIO, TORCH, WHISPER_MODEL_CLASS, TTFONT_CLASS
    if GRADIO is not None and TORCH is not None and WHISPER_MODEL_CLASS is not None:
        return

    import gradio as gr  # type: ignore
    import torch  # type: ignore
    from faster_whisper import WhisperModel  # type: ignore
    from fontTools.ttLib import TTFont  # type: ignore

    GRADIO = gr
    TORCH = torch
    WHISPER_MODEL_CLASS = WhisperModel
    TTFONT_CLASS = TTFont


def mount_drive(force_remount: bool = False) -> Path:
    """Mount the Colab Drive volume and return the project root."""

    try:
        from google.colab import drive  # type: ignore  # pragma: no cover
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "This script requires google.colab to mount Drive; "
            "set GOD_MODE_ROOT to bypass the mount in non-Colab environments"
        ) from exc

    mount_point = "/content/drive"
    LOGGER.info("Mounting Google Drive at %s", mount_point)
    drive.mount(mount_point, force_remount=force_remount)

    roots = ("/content/drive/My Drive/VideoRobot", "/content/drive/MyDrive/VideoRobot")
    for root in roots:
        path = Path(root)
        if path.exists():
            return path
    raise SystemExit("Missing /content/drive/MyDrive/VideoRobot – ensure the folder exists")


def resolve_project_root(force_remount: bool = False) -> Path:
    """Return the VideoRobot project root, honouring overrides."""

    override = os.environ.get("GOD_MODE_ROOT")
    if override:
        path = Path(override).expanduser()
        if not path.exists():
            raise SystemExit(f"GOD_MODE_ROOT={path} does not exist")
        return path

    if "google.colab" in sys.modules:
        return mount_drive(force_remount=force_remount)

    # Lazy import so local runs without Colab can still work via env override.
    try:
        __import__("google.colab")  # pragma: no cover - only on Colab
    except Exception:
        raise SystemExit(
            "Set GOD_MODE_ROOT to the VideoRobot directory when running outside Colab"
        )
    return mount_drive(force_remount=force_remount)


def _prepare_stage_dirs(base: Path) -> Tuple[Path, Path, Path]:
    assets = base / "assets"
    tmp = base / "tmp"
    cache = base / "cache"
    for directory in (base, assets, tmp, cache):
        directory.mkdir(parents=True, exist_ok=True)
    return assets, tmp, cache


def has_nvenc() -> bool:
    try:
        return "h264_nvenc" in run_cmd("ffmpeg -hide_banner -encoders", check=False).stdout
    except Exception:
        return False


@dataclass(frozen=True)
class ProjectPaths:
    drive: Path
    assets: Path
    output: Path
    stage_root: Path
    staged_assets: Path
    staged_tmp: Path
    staged_cache: Path


def _init_project_paths(force_remount: bool = False) -> ProjectPaths:
    drive_root = resolve_project_root(force_remount=force_remount)
    assets = drive_root / "Assets"
    output = drive_root / "Output"
    output.mkdir(parents=True, exist_ok=True)

    stage_root = Path("/content/_studio_cache")
    staged_assets, staged_tmp, staged_cache = _prepare_stage_dirs(stage_root)

    if not assets.exists():
        raise SystemExit("Expected an Assets folder inside the VideoRobot drive directory")
    return ProjectPaths(
        drive=drive_root,
        assets=assets,
        output=output,
        stage_root=stage_root,
        staged_assets=staged_assets,
        staged_tmp=staged_tmp,
        staged_cache=staged_cache,
    )


def discover_assets(paths: ProjectPaths) -> Tuple[List[str], List[str], List[str], List[str]]:
    assets = paths.assets
    audio = sorted(
        [f.name for f in assets.glob("*") if f.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}]
    )
    backgrounds = sorted(
        [f.name for f in assets.glob("*") if f.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    )
    mp4 = sorted([f.name for f in assets.glob("*.mp4")])
    fonts = sorted(
        [f.name for f in assets.glob("*") if f.suffix.lower() in {".ttf", ".otf"}]
    )
    if not audio or not backgrounds:
        raise SystemExit("Missing audio/background files in Assets")
    return audio, backgrounds, mp4, fonts


def stage_one(paths: ProjectPaths, name: Optional[str]) -> Optional[Path]:
    if not name or str(name).lower() == "none":
        return None
    src, dst = paths.assets / name, paths.staged_assets / name
    if not src.exists():
        LOGGER.warning("Missing asset: %s", src)
        return None
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        import shutil

        LOGGER.debug("Staging %s -> %s", src, dst)
        shutil.copy2(src, dst)
    return dst


def stage_parallel(paths: ProjectPaths, *names: Optional[str]) -> List[Optional[Path]]:
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(functools.partial(stage_one, paths), names))


def ensure_font_registered(font_path: Path) -> str:
    """Copy the selected font into the user font directory and return its name."""

    name = font_name(font_path)
    fdir = Path("~/.fonts").expanduser()
    fdir.mkdir(parents=True, exist_ok=True)
    target = fdir / font_path.name
    if not target.exists() or target.stat().st_size != font_path.stat().st_size:
        import shutil

        LOGGER.info("Installing custom font %s", font_path.name)
        shutil.copy2(font_path, target)
        run_cmd("fc-cache -fv", check=False, capture=False)
    return name


@dataclass
class RuntimeState:
    paths: ProjectPaths
    audio_list: List[str]
    background_list: List[str]
    mp4_list: List[str]
    font_list: List[str]
    device: str
    compute: str
    nvenc: bool


class WhisperModelCache:
    """LRU cache for Whisper models to cap GPU/CPU usage."""

    def __init__(self, device: str, compute: str, limit: int = 2) -> None:
        self.device = device
        self.compute = compute
        self.limit = limit
        self._models: "OrderedDict[str, Any]" = OrderedDict()

    def _dispose(self, model: Any) -> None:
        try:
            model.model.unload_model()  # type: ignore[attr-defined]
        except Exception:
            pass
        gc.collect()

    def get(self, name: str):
        if name in self._models:
            model = self._models.pop(name)
            self._models[name] = model
            return model

        load_dependencies()
        LOGGER.info("Loading Whisper model %s", name)
        model = WHISPER_MODEL_CLASS(  # type: ignore[operator]
            name,
            device=self.device,
            compute_type=self.compute,
        )
        self._models[name] = model
        while len(self._models) > self.limit:
            _, old = self._models.popitem(last=False)
            LOGGER.info("Unloading Whisper model to honour cache limit")
            self._dispose(old)
        return model


_RUNTIME: Optional[RuntimeState] = None
_MODEL_CACHE: Optional[WhisperModelCache] = None


def get_runtime(force_remount: bool = False) -> RuntimeState:
    global _RUNTIME, _MODEL_CACHE
    if _RUNTIME is not None:
        return _RUNTIME

    LOGGER.info("Bootstrapping God Mode runtime…")
    ensure_environment()
    load_dependencies()

    paths = _init_project_paths(force_remount=force_remount)
    audio, backgrounds, mp4, fonts = discover_assets(paths)
    device = "cuda" if TORCH.cuda.is_available() else "cpu"  # type: ignore[union-attr]
    compute = "int8_float16" if device == "cuda" else "int8"
    nvenc = has_nvenc()

    _RUNTIME = RuntimeState(
        paths=paths,
        audio_list=audio,
        background_list=backgrounds,
        mp4_list=mp4,
        font_list=fonts,
        device=device,
        compute=compute,
        nvenc=nvenc,
    )
    _MODEL_CACHE = WhisperModelCache(device=device, compute=compute)
    return _RUNTIME


def get_model_cache() -> WhisperModelCache:
    if _MODEL_CACHE is None:
        raise RuntimeError("Runtime not initialised; call get_runtime() first")
    return _MODEL_CACHE


def probe_dur(p: Optional[Path]) -> float:
    if not p or not p.exists():
        return 0.0
    try:
        return float(
            run_cmd(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(p),
                ],
                check=False,
            ).stdout.strip()
        )
    except Exception:
        return 0.0


def has_audio(p: Optional[Path]) -> bool:
    if not p or not p.exists():
        return False
    try:
        return bool(
            run_cmd(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "compact=p=0:nk=1",
                    str(p),
                ],
                check=False,
            ).stdout.strip()
        )
    except Exception:
        return False


def has_video(p: Optional[Path]) -> bool:
    if not p or not p.exists():
        return False
    try:
        return bool(
            run_cmd(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "compact=p=0:nk=1",
                    str(p),
                ],
                check=False,
            ).stdout.strip()
        )
    except Exception:
        return False


def font_name(path: Path) -> str:
    load_dependencies()
    try:
        ft = TTFONT_CLASS(str(path))  # type: ignore[arg-type]
        for r in ft["name"].names:
            if r.nameID == 4:
                try:
                    nm = r.toUnicode()
                    if nm:
                        return nm
                except Exception:
                    pass
        return path.stem
    except Exception:
        return path.stem


def bgr_hex(rgb_hex: str) -> str:
    h = rgb_hex.strip().lstrip("#").upper()
    return f"{h[4:6]}{h[2:4]}{h[0:2]}"


def ass_time(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    cs = int(round((s - int(s)) * 100))
    if cs == 100:
        s = int(s) + 1
        cs = 0
    return f"{int(h)}:{int(m):02d}:{int(s):02d}.{cs:02d}"


def chars_capacity(w: int, margin: int, fs: int) -> int:
    avail = max(80, w - 2 * margin)
    avg_char_px = max(1.0, 0.60 * fs)
    return max(8, int(avail / avg_char_px))


MAX_LINES = 2


def pack_lines(words: List[Dict], max_chars: int):
    def join(ws):
        return " ".join(w["text"] for w in ws)

    line1, line2, cur = [], [], []
    for w in words:
        cand = join(cur + [w])
        if len(cand) <= max_chars:
            cur.append(w)
        else:
            if not line1:
                line1, cur = cur, [w]
            elif not line2:
                line2, cur = cur, [w]
            else:
                break
    if not line1:
        line1, cur = cur, []
    elif not line2 and cur:
        line2, cur = cur, []
    used = [ln for ln in (line1, line2) if ln]
    return used, words[len(line1) + len(line2) :]


def split_events(words: List[Dict], max_chars: int, offset: float):
    ev, buf = [], words[:]
    while buf:
        lines, rest = pack_lines(buf, max_chars)
        if len(lines) > MAX_LINES:
            mid = len(buf) // 2
            cut = mid
            for i in range(max(1, mid - 3), min(len(buf) - 1, mid + 3)):
                if buf[i]["text"] and buf[i]["text"][-1] in ".!?,:;":
                    cut = i + 1
                    break
            left, right = buf[:cut], buf[cut:]
            lines, _ = pack_lines(left, max_chars)
            buf = right
        else:
            buf = rest
        if not lines:
            break
        st = lines[0][0]["start"] + offset
        en = lines[-1][-1]["end"] + offset
        allw = [w for line in lines for w in line]
        text = "\\N".join([" ".join(w["text"] for w in line) for line in lines])
        ev.append((st, en, text, allw))
    return ev


def build_ass(
    state: RuntimeState,
    audio_path: Path,
    font: str,
    fs: int,
    pos: str,
    margin_v: int,
    border: int,
    primary: str,
    hi: str,
    offset: float,
    model_name: str,
    vw: int = 1920,
    vh: int = 1080,
) -> Path:
    key = (
        f"{audio_path}:{audio_path.stat().st_mtime}:{audio_path.stat().st_size}:"
        f"{font}:{fs}:{pos}:{margin_v}:{border}:{primary}:{hi}:{int(offset*1000)}:{model_name}"
    )
    out = state.paths.staged_cache / f"{hashlib.sha1(key.encode()).hexdigest()}.ass"
    if out.exists():
        return out

    model = get_model_cache().get(model_name)
    segments, _ = model.transcribe(  # type: ignore[attr-defined]
        str(audio_path),
        language="en",
        vad_filter=True,
        vad_parameters=dict(threshold=0.5, min_speech_duration_ms=250),
        word_timestamps=True,
        beam_size=1,
        best_of=1,
    )
    words: List[Dict[str, Any]] = []
    for s in segments:
        if s.words:
            for w in s.words:
                t = (w.word or "").strip()
                if t:
                    words.append({"start": w.start, "end": w.end, "text": t})
    sents, buf = [], []
    for w in words:
        buf.append(w)
        if w["text"][-1] in ".?!":
            sents.append(buf)
            buf = []
    if buf:
        sents.append(buf)
    maxc = chars_capacity(vw, 80, fs)
    events: List[Tuple[float, float, str, List[Dict[str, Any]]]] = []
    for s in sents:
        events.extend(split_events(s, maxc, offset))
    align = {"Top": 8, "Middle": 5, "Bottom": 2}.get(pos, 2)
    p_bgr, h_bgr = bgr_hex(primary), bgr_hex(hi)
    with out.open("w", encoding="utf-8") as f:
        f.write(
            f"[Script Info]\nPlayResX: {vw}\nPlayResY: {vh}\nWrapStyle: 3\nScaledBorderAndShadow: yes\n\n"
        )
        f.write("** Aegisub Project Garbage **\n\n")
        f.write(
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
            "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
            "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        )
        f.write(
            f"Style: Default,{font},{fs},&H00{p_bgr},&H00{h_bgr},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,{border},2,{align},80,80,{margin_v},1\n\n"
        )
        f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        for st, en, txt, wl in events:
            total = int(round((en - st) * 100))
            k = []
            acc = 0
            for i, w in enumerate(wl):
                dur = int(round((w["end"] - w["start"]) * 100))
                if i == len(wl) - 1:
                    dur = max(1, total - acc)
                k.append(dur)
                acc += dur
            kt = "{\\q2}" + "".join([f"{{\\k{d}}}{wl[i]['text']}" for i, d in enumerate(k)])
            f.write(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Default,,0,0,0,,{kt}\n")
    return out


def validate_video_asset(label: str, path: Optional[Path]) -> Optional[Path]:
    if not path:
        return None
    if not has_video(path):
        raise ValueError(f"{label} lacks a video stream: {path}")
    return path


def build_filter_graph(
    state: RuntimeState,
    st_bg: Path,
    norm: Path,
    total: float,
    d_intro: float,
    d_main: float,
    d_outro: float,
    st_intro: Optional[Path],
    st_outro: Optional[Path],
    st_cta: Optional[Path],
    cta_times: List[float],
    d_cta: float,
    intro_chroma: bool,
    outro_chroma: bool,
    cta_key: str,
    cta_sim: float,
    cta_blend: float,
    cta_pos: str,
) -> Tuple[List[str], List[str]]:
    vf: List[str] = []
    af: List[str] = []
    bg_i = 0
    intro_i = 2 if st_intro and d_intro > 0 else None
    outro_offset = 2 + (1 if intro_i is not None else 0)
    outro_i = outro_offset if st_outro and d_outro > 0 else None
    cta_offset = 2
    if intro_i is not None:
        cta_offset += 1
    if outro_i is not None:
        cta_offset += 1
    cta_i = cta_offset if st_cta and d_cta > 0 else None

    vf.append(
        f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1:color=black,format=yuv420p,trim=duration={total:.3f},setsar=1[v0]"
    )
    cur = "v0"
    if intro_i is not None and st_intro:
        ck = (
            f",colorkey=0x00FF00:{cta_sim:.2f}:{cta_blend:.2f}"
            if intro_chroma
            else ""
        )
        vf.append(
            f"[{intro_i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1,fps=30,format=rgba{ck},trim=duration={d_intro:.3f}[intro]"
        )
        vf.append(
            f"[{cur}][intro]overlay=eof_action=pass:repeatlast=0:enable='between(t,0,{d_intro:.3f})'[v1]"
        )
        cur = "v1"
    if cta_i is not None and st_cta and cta_times:
        vf.append(
            f"[{cta_i}:v]scale=1152:-1:force_original_aspect_ratio=decrease,fps=30,format=rgba[cta0]"
        )
        vf.append(f"[cta0]split={len(cta_times)}" + "".join([f"[c{i}]" for i in range(len(cta_times))]))
        key_hex = "0x" + cta_key.lstrip("#").upper()
        cta_y = "20" if cta_pos == "Top" else "(H-h)/2" if cta_pos == "Middle" else "H-h-20"
        for i, st in enumerate(cta_times):
            en = st + d_cta
            vf.append(
                f"[c{i}]colorkey={key_hex}:{cta_sim:.2f}:{cta_blend:.2f},trim=duration={d_cta:.3f},setpts=PTS+{st:.3f}/TB[ct{i}]"
            )
            vf.append(
                f"[{cur}][ct{i}]overlay=x=(W-w)/2:y={cta_y}:eof_action=pass:repeatlast=0:enable='between(t,{st:.3f},{en:.3f})'[v{i+2}]"
            )
            cur = f"v{i+2}"
    if outro_i is not None and st_outro:
        start = d_intro + d_main
        ck = (
            f",colorkey=0x00FF00:{cta_sim:.2f}:{cta_blend:.2f}"
            if outro_chroma
            else ""
        )
        vf.append(
            f"[{outro_i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1,fps=30,format=rgba{ck},trim=duration={d_outro:.3f}[outro]"
        )
        vf.append(
            f"[{cur}][outro]overlay=eof_action=pass:repeatlast=0:enable='between(t,{start:.3f},{total:.3f})'[vX]"
        )
        cur = "vX"
    sub_esc = str((state.paths.staged_tmp / "s.ass")).replace(":", r"\:")
    fdir_esc = str(Path("~/.fonts").expanduser()).replace(":", r"\:")
    vf.append(f"[{cur}]subtitles='{sub_esc}':fontsdir='{fdir_esc}'[vF]")

    ain: List[str] = []
    if intro_i is not None and st_intro and has_audio(st_intro):
        af.append(f"[{intro_i}:a]aresample=48000[ia]")
        ain.append("[ia]")
    dly = int(d_intro * 1000)
    af.append(f"[1:a]adelay={dly}|{dly}[ma]")
    ain.append("[ma]")
    if outro_i is not None and st_outro and has_audio(st_outro):
        dly2 = int((d_intro + d_main) * 1000)
        af.append(f"[{outro_i}:a]adelay={dly2}|{dly2}[oa]")
        ain.append("[oa]")
    if cta_i is not None and st_cta and cta_times and has_audio(st_cta):
        af.append(f"[{cta_i}:a]aresample=48000[cb]")
        for i, st in enumerate(cta_times):
            dms = int(st * 1000)
            af.append(
                f"[cb]atrim=0:{d_cta:.3f},asetpts=PTS-STARTPTS,adelay={dms}|{dms}[c{i}a]"
            )
            ain.append(f"[c{i}a]")
    if len(ain) > 1:
        af.append(
            f"{''.join(ain)}amix=inputs={len(ain)}:duration=longest:normalize=0,dynaudnorm=f=150:g=15,alimiter=limit=0.95[aF]"
        )
    elif len(ain) == 1:
        af.append(f"{ain[0]}dynaudnorm=f=150:g=15,alimiter=limit=0.95[aF]")
    else:
        af.append(f"anullsrc=r=48000:cl=stereo:d={total:.3f}[aF]")
    return vf, af


def render_video(
    audio,
    bg,
    wsize,
    fontfile,
    fsize,
    color,
    hicolor,
    border,
    cpos,
    margin_v,
    intro,
    intro_chroma,
    outro,
    outro_chroma,
    cta,
    cta_start,
    cta_repeat,
    cta_key,
    cta_sim,
    cta_blend,
    cta_pos,
    progress=None,
):
    state = get_runtime()
    if progress is None:
        from gradio import Progress  # lazy import for runtime

        progress = Progress()
    VW, VH = 1920, 1080
    try:
        LOGGER.info(
            "Render request received",
            extra={
                "audio": audio,
                "background": bg,
                "intro": intro,
                "outro": outro,
                "cta": cta,
                "whisper": wsize,
            },
        )
        progress(0.05, desc="stage")
        st_audio, st_bg, st_intro, st_outro, st_cta = stage_parallel(
            state.paths, audio, bg, intro, outro, cta
        )
        if not st_audio:
            return None, f"Audio not found: {audio}"
        if not st_bg:
            return None, f"Background not found: {bg}"
        validate_video_asset("Background", st_bg)
        if st_intro:
            validate_video_asset("Intro", st_intro)
        if st_outro:
            validate_video_asset("Outro", st_outro)
        if st_cta:
            validate_video_asset("CTA", st_cta)
        progress(0.10, desc="fonts")
        fname = "DejaVu Sans"
        if fontfile and str(fontfile).lower() != "none":
            fp = state.paths.assets / fontfile
            if fp.exists():
                fname = ensure_font_registered(fp)
        progress(0.15, desc="audio")
        norm = state.paths.staged_tmp / "audio.m4a"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(st_audio),
                "-af",
                "loudnorm=I=-16:LRA=11:TP=-1.5,aresample=48000",
                "-ac",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(norm),
            ]
        )
        progress(0.22, desc="timing")
        d_intro = probe_dur(st_intro) if st_intro else 0.0
        d_outro = probe_dur(st_outro) if st_outro else 0.0
        d_main = probe_dur(norm)
        total = d_intro + d_main + d_outro
        offset = d_intro
        progress(0.33, desc="captions")
        subf = build_ass(
            state,
            norm,
            fname,
            int(fsize),
            cpos,
            int(margin_v),
            int(border),
            color,
            hicolor,
            offset,
            wsize,
            VW,
            VH,
        )
        import shutil

        work_ass = state.paths.staged_tmp / "s.ass"
        shutil.copy2(subf, work_ass)
        progress(0.50, desc="graph")
        inputs = []
        inputs += ["-thread_queue_size", "512", "-f", "image2", "-loop", "1", "-framerate", "30", "-i", str(st_bg)]
        inputs += ["-thread_queue_size", "512", "-i", str(norm)]
        if st_intro and d_intro > 0:
            inputs += ["-thread_queue_size", "512", "-i", str(st_intro)]
        if st_outro and d_outro > 0:
            inputs += ["-thread_queue_size", "512", "-i", str(st_outro)]
        d_cta = probe_dur(st_cta) if st_cta else 0.0
        cta_times: List[float] = []
        if st_cta and d_cta > 0 and cta_repeat > 0:
            if st_cta:
                inputs += ["-thread_queue_size", "512", "-i", str(st_cta)]
            t = offset + cta_start
            while t < total - 0.1 and len(cta_times) < 50:
                cta_times.append(t)
                t += cta_repeat
        vf, af = build_filter_graph(
            state,
            st_bg,
            norm,
            total,
            d_intro,
            d_main,
            d_outro,
            st_intro,
            st_outro,
            st_cta,
            cta_times,
            d_cta,
            intro_chroma,
            outro_chroma,
            cta_key,
            cta_sim,
            cta_blend,
            cta_pos,
        )
        filter_complex = ";".join(vf + af)
        progress(0.70, desc="encode")
        if state.nvenc:
            vcodec = [
                "-c:v",
                "h264_nvenc",
                "-preset",
                os.environ.get("GOD_MODE_NVENC_PRESET", "p4"),
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                os.environ.get("GOD_MODE_NVENC_CQ", "20"),
                "-b:v",
                os.environ.get("GOD_MODE_NVENC_BITRATE", "5M"),
                "-maxrate",
                os.environ.get("GOD_MODE_NVENC_MAXRATE", "7M"),
                "-bufsize",
                os.environ.get("GOD_MODE_NVENC_BUFSIZE", "10M"),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ]
        else:
            vcodec = [
                "-c:v",
                os.environ.get("GOD_MODE_X264_ENCODER", "libx264"),
                "-preset",
                os.environ.get("GOD_MODE_X264_PRESET", "fast"),
                "-crf",
                os.environ.get("GOD_MODE_X264_CRF", "21"),
                "-g",
                os.environ.get("GOD_MODE_X264_GOP", "60"),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ]
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        outp = state.paths.output / f"{ts}_{Path(audio).stem}_1920x1080_PRO.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-threads",
            "0",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vF]",
            "-map",
            "[aF]",
            "-t",
            str(total),
            "-r",
            "30",
            *vcodec,
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ac",
            "2",
            str(outp),
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        last = 0.70
        buf: List[str] = []
        while True:
            ln = proc.stderr.readline()
            if not ln:
                break
            buf.append(ln)
            if "time=" in ln:
                try:
                    t = ln.split("time=")[1].split()[0]
                    h, m, s = t.split(":")
                    cur = float(h) * 3600 + float(m) * 60 + float(s)
                    if total > 0:
                        pr = min(cur / total, 1.0)
                        nv = 0.70 + pr * 0.25
                        if nv > last + 0.01:
                            progress(nv, desc=f"encode {int(pr * 100)}%")
                            last = nv
                except Exception:
                    pass
        proc.wait()
        if proc.returncode != 0:
            return None, "FFmpeg failed:\n" + ("".join(buf)[-2000:])
        progress(0.98, desc="cleanup")
        try:
            for tfile in state.paths.staged_tmp.glob("*"):
                if tfile.is_file():
                    tfile.unlink()
        except Exception:
            pass
        progress(1.0, desc="done")
        sz = outp.stat().st_size / (1024 * 1024)
        return (
            str(outp),
            f"✅ Rendered\n{outp.name}\n{sz:.1f} MB\n{total:.1f}s\n1920x1080@30\nNVENC:{'on' if state.nvenc else 'off'}",
        )
    except Exception as exc:
        import traceback

        LOGGER.exception("Render failed")
        return None, "Failed:\n" + traceback.format_exc()


def ui(force_remount: bool = False):
    state = get_runtime(force_remount=force_remount)
    load_dependencies()
    theme = GRADIO.themes.Soft(primary_hue="blue", secondary_hue="cyan", neutral_hue="slate")
    with GRADIO.Blocks(theme=theme, title="God Mode v27-PRO") as app:
        GRADIO.HTML(
            f'<div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:1.25rem;border-radius:1rem;margin-bottom:1rem;color:#fff;text-align:center;">'
            f'<h1 style="margin:0">🎬 God Mode v27-PRO</h1>'
            f'<div style="opacity:.9">Hardware: {state.device.upper()} • NVENC: {"✅" if state.nvenc else "❌"}</div>'
            "</div>"
        )
        with GRADIO.Row():
            with GRADIO.Column(scale=1):
                with GRADIO.Accordion("🎵 Main", open=True):
                    a = GRADIO.Dropdown(choices=state.audio_list, value=state.audio_list[0], label="Audio")
                    b = GRADIO.Dropdown(choices=state.background_list, value=state.background_list[0], label="Background")
                    w = GRADIO.Radio(choices=["large-v3", "medium", "small"], value="small", label="Whisper")
                with GRADIO.Accordion("🔤 Font", open=False):
                    ff = GRADIO.Dropdown(choices=["None"] + state.font_list, value="None", label="Font file")
                with GRADIO.Accordion("📝 Captions", open=True):
                    fs = GRADIO.Slider(30, 100, 58, 2, label="Size")
                    col = GRADIO.ColorPicker("#FFFFFF", label="Color")
                    hi = GRADIO.ColorPicker("#FFFF00", label="Highlight")
                    brd = GRADIO.Slider(1, 12, 3, 1, label="Border")
                    pos = GRADIO.Radio(["Top", "Middle", "Bottom"], value="Bottom", label="Position")
                    mar = GRADIO.Slider(0, 400, 80, 10, label="Vertical margin")
                with GRADIO.Accordion("🎬 Intro/Outro", open=False):
                    intro = GRADIO.Dropdown(["None"] + state.mp4_list, value="None", label="Intro")
                    intro_ck = GRADIO.Checkbox(False, label="Chroma Key Intro")
                    outro = GRADIO.Dropdown(["None"] + state.mp4_list, value="None", label="Outro")
                    outro_ck = GRADIO.Checkbox(False, label="Chroma Key Outro")
                with GRADIO.Accordion("📢 CTA", open=False):
                    c = GRADIO.Dropdown(["None"] + state.mp4_list, value="None", label="CTA Loop")
                    cpos = GRADIO.Radio(["Top", "Middle", "Bottom"], value="Middle", label="CTA Position")
                    cstart = GRADIO.Slider(5, 300, 30, 5, label="Start (s)")
                    crep = GRADIO.Slider(10, 600, 120, 10, label="Repeat (s)")
                    ckey = GRADIO.ColorPicker("#00FF00", label="Key Color")
                    cs = GRADIO.Slider(0.01, 1.0, 0.42, 0.01, label="Similarity")
                    cb = GRADIO.Slider(0.0, 1.0, 0.08, 0.01, label="Blend")
                btn = GRADIO.Button("🎬 Render", variant="primary", size="lg")
            with GRADIO.Column(scale=2):
                v = GRADIO.Video(label="📹 Output", height=480)
                s = GRADIO.Textbox(label="📊 Status", lines=8, max_lines=12)
        btn.click(
            render_video,
            [
                a,
                b,
                w,
                ff,
                fs,
                col,
                hi,
                brd,
                pos,
                mar,
                intro,
                intro_ck,
                outro,
                outro_ck,
                c,
                cstart,
                crep,
                ckey,
                cs,
                cb,
                cpos,
            ],
            [v, s],
        )
    return app


if __name__ == "__main__":
    state = get_runtime()
    print(
        f"\n=== God Mode v27-PRO ===\n"
        f"Assets: {state.paths.assets}\n"
        f"Output: {state.paths.output}\n"
        f"Device: {state.device}\n"
        f"NVENC: {state.nvenc}\n"
    )
    application = ui()
    application.queue()
    application.launch()
