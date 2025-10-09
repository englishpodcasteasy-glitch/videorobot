"""Renderer queue and HTTP blueprint for the deterministic render pipeline."""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_file
from jsonschema import Draft7Validator
from moviepy import editor as mpe

from .config import Paths
from .renderer import VideoComposer
from .utils import ensure_outputs_dir, install_ffmpeg_if_needed

log = logging.getLogger("VideoRobot.renderer_service")

renderer_bp = Blueprint("renderer_service", __name__)
_queue_instance: Optional["RendererQueue"] = None


def _ok(data: Dict[str, Any], status_code: int = 200):
    response = jsonify({"ok": True, "data": data, "error": None})
    return response, status_code


def _err(message: str, status_code: int, *, details: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
    payload: Dict[str, Any] = {"ok": False, "data": None, "error": message}
    if details:
        payload["details"] = details
    response = jsonify(payload)
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    return response, status_code


class QueueFullError(RuntimeError):
    """Raised when the renderer queue cannot accept more work."""


class RendererQueue:
    """Threaded renderer queue with deterministic MoviePy backend."""

    def __init__(
        self,
        paths: Optional[Paths] = None,
        *,
        max_workers: int = 2,
        max_inflight: int = 3,
    ) -> None:
        global _queue_instance

        self._paths = paths
        self._output_root = ensure_outputs_dir()
        self._output_root.mkdir(parents=True, exist_ok=True)
        self._max_inflight = max_inflight
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="renderer-worker")
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._log = logging.getLogger("VideoRobot.renderer_queue")
        _queue_instance = self
        self._log.info("RendererQueue ready (root=%s, max_inflight=%d)", self._output_root, max_inflight)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        if not self._can_accept():
            raise QueueFullError("renderer queue is full")

        job_id = uuid.uuid4().hex
        job_dir = self._output_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        composer = VideoComposer()
        _, _, inputs_hash = composer.prepare_manifest(manifest, job_dir)

        job = {
            "job_id": job_id,
            "state": "queued",
            "pct": 0,
            "message": "queued",
            "workdir": job_dir.as_posix(),
            "created_at": time.time(),
            "updated_at": time.time(),
            "inputs_sha256": inputs_hash,
            "result": {},
        }

        with self._lock:
            self._jobs[job_id] = job

        self._executor.submit(self._process_job, job_id, manifest, job_dir)
        return {"job_id": job_id, "workdir": job_dir.as_posix(), "inputs_sha256": inputs_hash}

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def find_output(self, filename: str) -> Optional[Path]:
        if not filename or Path(filename).name != filename:
            return None

        with self._lock:
            for job in self._jobs.values():
                result = job.get("result") or {}
                mp4 = result.get("mp4")
                if mp4 and Path(mp4).name == filename:
                    path = Path(mp4)
                    if path.exists():
                        return path

        candidate = self._output_root / filename
        if candidate.exists():
            return candidate

        for path in self._output_root.glob(f"*/{filename}"):
            if path.is_file():
                return path
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _can_accept(self) -> bool:
        with self._lock:
            inflight = sum(1 for job in self._jobs.values() if job.get("state") in {"queued", "running"})
            return inflight < self._max_inflight

    def _update_job(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(fields)
            job["updated_at"] = time.time()

    def _process_job(self, job_id: str, manifest: Dict[str, Any], job_dir: Path) -> None:
        self._update_job(job_id, state="running", pct=10, message="initialising renderer")

        try:
            install_ffmpeg_if_needed()
            self._update_job(job_id, pct=20, message="loading assets")

            composer = VideoComposer()
            result_path = composer.compose(manifest, job_dir)
            self._update_job(job_id, pct=70, message="encoding complete")
            duration_ms = composer.last_duration_ms
            if duration_ms is None:
                probe = mpe.VideoFileClip(str(result_path))
                duration_ms = int(probe.duration * 1000)
                probe.close()
            duration_ms = int(duration_ms)
            inputs_hash = composer.last_inputs_sha256 or (job_dir / "inputs.sha256").read_text(encoding="utf-8").strip()
            manifest_path = composer.manifest_path or (job_dir / "manifest_canonical.json")

            self._update_job(job_id, pct=95, message="finalising output")
            self._write_report(job_id, job_dir, manifest_path, result_path, duration_ms, inputs_hash)
            self._maybe_copy_output(result_path)

            self._update_job(
                job_id,
                state="success",
                pct=100,
                message="completed",
                result={"mp4": result_path.as_posix()},
                inputs_sha256=inputs_hash,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            self._log.exception("Renderer job %s failed", job_id)
            error_info = {
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            (job_dir / "error.json").write_text(json.dumps(error_info, ensure_ascii=False, indent=2), encoding="utf-8")
            self._update_job(
                job_id,
                state="error",
                pct=100,
                message=str(exc),
                error=str(exc),
            )

    def _write_report(
        self,
        job_id: str,
        job_dir: Path,
        manifest_path: Path,
        result_path: Path,
        duration_ms: int,
        inputs_hash: str,
    ) -> None:
        report = {
            "job_id": job_id,
            "manifest": manifest_path.name,
            "inputs_sha256": inputs_hash,
            "final_path": result_path.as_posix(),
            "duration_ms": duration_ms,
        }
        (job_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def _maybe_copy_output(self, result_path: Path) -> None:
        if not self._paths or not getattr(self._paths, "out_local", None):
            return
        try:
            dest_dir = self._paths.out_local  # type: ignore[union-attr]
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / result_path.name
            if target.resolve() == result_path.resolve():
                return
            import shutil

            shutil.copy2(result_path, target)
        except Exception as exc:  # pragma: no cover - runtime guard
            self._log.warning("Failed to copy result to %s: %s", self._paths.out_local, exc)


# ----------------------------------------------------------------------
# Schema validation helpers
# ----------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "render_manifest.schema.json"
_MANIFEST_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_MANIFEST_VALIDATOR = Draft7Validator(_MANIFEST_SCHEMA)


def _validate_manifest(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    errors = sorted(_MANIFEST_VALIDATOR.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return None

    details = []
    for error in errors:
        location = "/".join(str(x) for x in error.path) or "<root>"
        details.append(f"{location}: {error.message}")
    return {"errors": details}


def _queue() -> RendererQueue:
    if _queue_instance is None:
        raise RuntimeError("RendererQueue not initialised")
    return _queue_instance


@renderer_bp.post("/render")
def render_route():
    try:
        payload = request.get_json(force=True)  # type: ignore[assignment]
    except Exception as exc:  # pragma: no cover - request guard
        return _err(f"invalid JSON: {exc}", 400)

    if not isinstance(payload, dict):
        return _err("payload must be an object", 400)

    validation = _validate_manifest(payload)
    if validation:
        return _err("manifest validation failed", 400, details=validation)

    try:
        info = _queue().enqueue(payload)
    except QueueFullError:
        retry_after = 10
        return _err(
            "renderer queue is full, retry later",
            429,
            details={"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    except FileNotFoundError as exc:
        return _err(str(exc), 400)

    return _ok(info)


@renderer_bp.get("/progress/<job_id>")
def progress_route(job_id: str):
    job = _queue().get_job(job_id)
    if not job:
        return _err("job not found", 404)
    return _ok(
        {
            "job_id": job["job_id"],
            "state": job["state"],
            "pct": job.get("pct", 0),
            "message": job.get("message", ""),
            "result": job.get("result", {}),
            "inputs_sha256": job.get("inputs_sha256"),
            "error": job.get("error"),
            "duration_ms": job.get("duration_ms"),
        }
    )


@renderer_bp.get("/status")
def status_route():
    job_id = (request.args.get("jobId") or request.args.get("id") or "").strip()
    if not job_id:
        return _err("jobId parameter is required", 400)
    job = _queue().get_job(job_id)
    if not job:
        return _err("job not found", 404)
    return _ok(job)


@renderer_bp.get("/download")
def download_route():
    job_id = (request.args.get("jobId") or request.args.get("id") or "").strip()
    if job_id:
        job = _queue().get_job(job_id)
        if not job:
            return _err("job not found", 404)
        if job.get("state") != "success":
            return _err("job not completed", 409)
        result = job.get("result") or {}
        mp4 = result.get("mp4")
        if not mp4:
            return _err("result not available", 404)
        path = Path(mp4)
        if not path.exists():
            return _err("output missing on disk", 404)
        return send_file(path, as_attachment=True, download_name=path.name)

    filename = request.args.get("file")
    if filename:
        path = _queue().find_output(filename)
        if not path:
            return _err("file not found", 404)
        return send_file(path, as_attachment=True, download_name=path.name)

    return _err("jobId or file parameter is required", 400)


__all__ = ["RendererQueue", "renderer_bp"]
