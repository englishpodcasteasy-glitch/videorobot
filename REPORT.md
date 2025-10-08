# REPORT

## Inventory

### Backend (`backend/`)
- Key modules: `main.py` (HTTP API), `renderer_service.py` (queue + API), `renderer.py` (MoviePy-based deterministic composer), `config.py`, `scheduler.py`, and `utils.py`.
- Requirements: `backend/requirements.txt` (pip) now bundles Flask/Whisper plus rendering deps (`moviepy`, `imageio-ffmpeg`, `opencv-python-headless>=4.10`, `jsonschema`, `Pillow`, `numpy>=1.26`).
- Schema: `backend/schemas/render_manifest.schema.json` validates render manifests before they enter the queue.
- Environment template: `backend/.env.example` (defines `BACKEND_PORT`, `CORS_ALLOW_ORIGIN`, `CF_TUNNEL_HOSTNAME`, `VR_VERSION`).
- Run entrypoint: `python backend/main.py` (reads `BACKEND_PORT`, defaults 8000).

### Frontend (`frontend/`)
- Static assets: `index.html`, `main.js`, plus supporting HTML docs (`analytics.html`, `projects.html`, etc.).
- Environment template: `frontend/.env.example` (exposes `VITE_API_BASE_URL`).
- No build tooling detected (vanilla static bundle, no package.json).

### Root / Scripts / Docs
- Root `requirements.txt` mirrors backend dependencies for convenience.
- Helper scripts: `scripts/run_cloudflare_tunnel.sh` (wraps `cloudflared` with env token guard) and `scripts/install_ffmpeg_colab.sh` (installs FFmpeg on fresh Colab runtimes).
- Documentation & API maps: `docs/api_contract_backend.json`, `docs/api_contract_frontend.json`, `docs/api_harmony_report.json`, plus this report.

## Harmony
- Frontend performs no live API requests; all backend endpoints are currently unused by the UI.
- Backend exposes `/health`, `/healthz`, `/version`, `/list-files`, `/transcribe`, `/render`, `/progress/<job_id>`, `/status`, `/download`.
- Harmony diff shows zero frontend calls missing on the backend and nine backend endpoints not yet consumed by the frontend (see `docs/api_harmony_report.json`).

## Changes per PR
- **PR-1 Backend Sync (feat/audit-sync):** Added health/version endpoints, response envelope helpers, strict CORS allow-list handling, `/status` integration with the renderer queue, and generated API contract docs.
- **PR-2 Frontend Sync:** Established environment-driven API base via `.env.example`; frontend remains static with placeholders pending integration.
- **PR-3 Renderer (Colab):** Upgraded `renderer_service.py` with JSON Schema validation, bounded threading, progress tracking, and wired it to the new MoviePy-based `renderer.py` deterministic composer.
- **PR-4 Tunnel & Scripts:** Added Cloudflare tunnel runner script, FFmpeg bootstrapper for Colab, and environment knobs for tunnel-aware CORS.
- **PR-5 Docs:** Authored `REPORT.md` and JSON harmony manifests describing the repository state and operational guidance.

## How to Run

### Local
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r backend/requirements.txt`
3. `cp backend/.env.example backend/.env` (override values as needed)
4. `python backend/main.py`
5. Access `http://127.0.0.1:8000/health` to verify service.

### Colab GPU
1. Clone the repository inside `/content` and install dependencies: `pip install -r backend/requirements.txt`.
2. Ensure FFmpeg is present (fresh runtimes need this once): `bash scripts/install_ffmpeg_colab.sh`.
3. Export `BACKEND_PORT=8000` (and optionally `CF_TUNNEL_HOSTNAME`).
4. Launch the backend: `python backend/main.py` — this boots the Flask API and renderer queue.
5. Save a manifest JSON similar to the example in the README (e.g. `/content/manifest.json`).
6. Submit a render: `curl -X POST http://127.0.0.1:8000/render -H 'Content-Type: application/json' -d @/content/manifest.json`.
7. Poll progress: `curl http://127.0.0.1:8000/progress/<job_id>` or `curl http://127.0.0.1:8000/status?jobId=<job_id>` until the state becomes `success`.
8. Download the MP4: `curl -OJ "http://127.0.0.1:8000/download?jobId=<job_id>"` (files land under `/content/outputs/<job_id>/final.mp4`).
9. Optional: run `scripts/run_cloudflare_tunnel.sh` after installing `cloudflared` and exporting `CF_TUNNEL_TOKEN` to expose the backend securely.

## Next Steps for Operators
- Copy the provided `.env.example` files to `.env` in both `backend/` and `frontend/`, then fill in any organization-specific values (for example the CORS origin or a Cloudflare tunnel hostname).
- Start the backend with `python backend/main.py` and keep the terminal open; this launches both the core API and the renderer queue.
- Use the curl examples above to submit a render job and verify that each run creates `/content/outputs/<job_id>/final.mp4` (or `./outputs/<job_id>/final.mp4` locally) along with `manifest_canonical.json` and `inputs.sha256`.
- If you need remote access, install `cloudflared`, export `CF_TUNNEL_TOKEN`, and run `scripts/run_cloudflare_tunnel.sh` in a separate terminal to create the secure tunnel the backend expects.
- When satisfied with results, commit any configuration changes to your private environment only—do **not** check secrets into version control.

## راهنمای سریع برای شما (بدون نیاز به دانش برنامه‌نویسی)
1. **دریافت پیش‌نیازها:** اگر روی لپ‌تاپ یا کلاب کار می‌کنید، ابتدا Python را فعال کنید و دستور `pip install -r backend/requirements.txt` را اجرا کنید تا همه کتابخانه‌های لازم نصب شوند.
2. **تنظیم فایل‌های محیطی:** از روی `backend/.env.example` و `frontend/.env.example` یک نسخه با نام `.env` بسازید. فقط مقدارهایی را که می‌دانید (مثل آدرس مجاز CORS یا نام تونل Cloudflare) تکمیل کنید؛ بقیه را دست نخورده بگذارید.
3. **راه‌اندازی سرویس:** در ترمینال دستور `python backend/main.py` را اجرا کنید و صبر کنید پیام «Server started» ظاهر شود. تا زمانی که سرویس فعال است این پنجره باید باز بماند.
4. **آزمایش ساده:** در یک ترمینال دیگر دستور زیر را بزنید تا مطمئن شوید سرویس سالم است: `curl http://127.0.0.1:8000/healthz`. اگر پاسخ `{"ok": true}` دیدید یعنی همه‌چیز آماده است.
5. **درخواست رندر نمونه:** ابتدا یک فایل `manifest.json` با محتوای ساده بسازید (مثلاً فقط یک متن روی پس‌زمینه):
   ```bash
   cat <<'EOF' > manifest.json
   {
     "seed": 7,
     "video": {"width": 720, "height": 1280, "fps": 30, "bg_color": "#101318"},
     "tracks": [
       {"type": "text", "content": "سلام دنیا", "start": 0.2, "duration": 3, "x": 40, "y": 80, "size": 72, "color": "#FFFFFF"}
     ]
   }
   EOF
   curl -X POST http://127.0.0.1:8000/render \
     -H 'Content-Type: application/json' \
     -d @manifest.json
   ```
   سرویس یک `job_id` به شما می‌دهد؛ آن را کپی کنید.
6. **بررسی پیشرفت رندر:** با همان `job_id` دستور `curl http://127.0.0.1:8000/progress/<job_id>` را اجرا کنید تا ببینید کار چه زمانی تمام می‌شود. پس از اتمام، فایل ویدیو را در پوشه `outputs/<job_id>/final.mp4` (یا روی کلاب `content/outputs/<job_id>/final.mp4`) پیدا می‌کنید. در صورت نیاز می‌توانید با `curl -OJ "http://127.0.0.1:8000/download?jobId=<job_id>"` خروجی را دانلود کنید.
7. **اشتراک‌گذاری امن:** اگر می‌خواهید از بیرون به سرویس وصل شوید، برنامه `cloudflared` را نصب کنید، متغیر `CF_TUNNEL_TOKEN` را تنظیم کنید و سپس دستور `scripts/run_cloudflare_tunnel.sh` را اجرا کنید. این کار بدون نیاز به تنظیمات پیچیده یک آدرس امن به شما می‌دهد.
8. **یادداشت مهم:** هرگز مقادیر حساس (توکن‌ها، رمزها) را داخل فایل‌های پروژه ذخیره و commit نکنید؛ فقط در محیط خودتان نگه دارید.

## Known Gaps
- Frontend lacks real API integration; follow-up work should wire UI controls to `/render` and `/progress` using the centralized base URL.
- Renderer composes layers via MoviePy but lacks advanced editing features (e.g., keyframed effects, complex transitions) that future iterations may add.
- No automated tests cover the new renderer queue.

## Notes
- `/version` reports `VR_VERSION` and `GIT_COMMIT` environment variables when set; defaults ensure safe responses during local runs.
