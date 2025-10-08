# REPORT

## Inventory

```
backend/
  main.py, renderer.py, renderer_service.py, config.py, scheduler.py, utils.py
  schemas/render_manifest.schema.json
frontend/
  index.html, main.js, analytics.html, projects.html, templates.html, design docs
scripts/
  install_ffmpeg_colab.sh, run_cloudflare_tunnel.sh
docs/
  api_contract_backend.json, api_contract_frontend.json, api_harmony_report.json
  manifest_examples/{simple_text.json,image_overlay.json,video_audio_mix.json}
notebooks/
  README.md
colab_runner.ipynb
.editorconfig, .pre-commit-config.yaml, pyproject.toml, Makefile, VERSION
```

### Backend (`backend/`)
- ماژول‌های اصلی: `main.py` (HTTP API + CORS + health/version)، `renderer_service.py` (صف چندنخی با محدودیت و اعتبارسنجی JSON Schema)، `renderer.py` (ترکیب‌کننده MoviePy قطعی)، به‌همراه `config.py`, `scheduler.py`, `utils.py`.
- وابستگی‌ها: `backend/requirements.txt` با پین دقیق (`Flask>=2.3,<3`, `moviepy>=1.0.3,<2`, `imageio-ffmpeg>=0.4.9,<1`, `opencv-python-headless>=4.10,<5`, `numpy>=1.26,<3`, `jsonschema>=4.23,<5`, `Pillow>=10,<11`, `requests>=2.31,<3`, `ctranslate2`, `faster-whisper`, ...).
- محیط: `backend/.env.example` پارامترهای `BACKEND_PORT`, `CORS_ALLOW_ORIGIN`, `CF_TUNNEL_HOSTNAME`, `VR_VERSION` را معرفی می‌کند؛ فایل `VERSION` مقدار پیش‌فرض `0.1.0` را تعیین کرده و در صورت نبود متغیر محیطی استفاده می‌شود.
- اجرا: `python -m backend.main` یا هدف `make run`؛ ساختار لوگ به stdout هدایت می‌شود.

### Frontend (`frontend/`)
- مجموعه صفحات استاتیک بدون bundler؛ `frontend/main.js` منطق UI را به‌علاوه بررسی سلامت API نگه می‌دارد.
- تماس شبکه: `main.js` با استفاده از `fetch` مسیر `/healthz` را فراخوانی و وضعیت را در ناوبری نمایش می‌دهد. مبنای URL از یکی از متغیرهای سراسری (`window.VIDEOROBOT_API_BASE_URL`, `window.VITE_API_BASE_URL`, `window.API_BASE_URL`) یا مقدار پیش‌فرض `http://127.0.0.1:8000` استخراج می‌شود.
- محیط: `frontend/.env.example` مقدار نمونه `VITE_API_BASE_URL` را فراهم می‌کند تا در buildهای آینده یا اسکریپت‌های inline مصرف شود.

### Scripts / Tooling / Docs
- اسکریپت‌ها: `scripts/install_ffmpeg_colab.sh` (نصب FFmpeg در Colab) و `scripts/run_cloudflare_tunnel.sh` (راه‌اندازی تونل Cloudflare با `CF_TUNNEL_TOKEN`).
- ابزار توسعه: `.editorconfig`, `pyproject.toml`, `.pre-commit-config.yaml` و اهداف `Makefile` (`setup`, `run`, `test`, `lint`, `format`, `colab-badge-check`).
- مستندات: `docs/api_contract_backend.json`, `docs/api_contract_frontend.json`, `docs/api_harmony_report.json`, به‌اضافه نمونه‌های مانیفست در `docs/manifest_examples/` و نوت‌بوک خودکار `colab_runner.ipynb`.

## Harmony
- فرانت‌اند اکنون تنها مسیر `/healthz` را مصرف می‌کند تا وضعیت API نمایش داده شود.
- بک‌اند مسیرهای `/health`, `/healthz`, `/version`, `/list-files`, `/transcribe`, `/render`, `/progress/<job_id>`, `/status`, `/download` را ارائه می‌دهد و همه پاسخ‌ها در قالب `{ok,data,error}` هستند.
- گزارش `docs/api_harmony_report.json` نشان می‌دهد که `/healthz` در فرانت‌اند استفاده می‌شود و سایر مسیرها هنوز مشتری UI ندارند؛ عدم انطباقی ثبت نشده است.

## Changes per PR
- **PR-SEC-1 — Security & Hygiene Baseline:** افزودن `.editorconfig`, `pyproject.toml`, `.pre-commit-config.yaml`, به‌روزرسانی `.gitignore` برای `.env`، و پین دقیق وابستگی‌های بک‌اند و ریشه.
- **PR-BE-2 — Backend Packaging & API Stability:** تبدیل `backend` به پکیج واقعی، تنظیم مسیر اجرایی `python -m backend.main`, بهبود پاسخ `/version` با تکیه بر فایل `VERSION`, و نگه‌داشت CORS محدود.
- **PR-REN-3 — Deterministic Renderer + FFmpeg bootstrap:** تکمیل `renderer.py` و `renderer_service.py` با صف محدود، هش ورودی‌ها، گزارش `report.json`, و نصب FFmpeg در زمان اجرا.
- **PR-TUN-4 — Tunnel & CORS Allowlist:** اسکریپت Cloudflare Tunnel و اضافه‌کردن `CF_TUNNEL_HOSTNAME` به مبداهای مجاز هنگام حضور.
- **PR-FE-5 — Minimal API Wiring & Env:** اتصال `frontend/main.js` به `/healthz`، نمایش نشان وضعیت، و حفظ `.env.example` فرانت‌اند.
- **PR-NB-6 — Colab notebook + Google Drive mount:** ساخت `colab_runner.ipynb` با کلون خودکار مخزن، نصب وابستگی‌ها، Mount Google Drive، ارسال job نمونه و توقف سرویس.
- **PR-CI-7 — CI, Pre-commit, and Release Pipeline:** افزودن GitHub Actions (`ci.yml`, `release.yml`)، اهداف `Makefile` و بررسی‌های pre-commit در CI.
- **PR-DOC-8 — Docs, examples, and troubleshooting:** بازنویسی README، افزودن `docs/manifest_examples/`, ایجاد `notebooks/`, و به‌روزرسانی این گزارش با راهنماهای اجرایی جدید.

## How to Run

### Local
1. `python -m venv .venv && source .venv/bin/activate`
2. `make setup` (نصب وابستگی‌ها و هوک‌های pre-commit)
3. `cp backend/.env.example backend/.env` و در صورت نیاز مقادیر را تغییر دهید (به‌ویژه `CORS_ALLOW_ORIGIN` و `VR_VERSION`).
4. `make run` (یا `python -m backend.main`)
5. صحت سرویس را با `curl http://127.0.0.1:8000/healthz` بررسی کنید؛ خروجی باید `{"ok": true, ...}` باشد.
6. برای اجرای lint/test از `make lint`, `make format`, `make test` استفاده کنید.

### Colab GPU
1. از README روی نشان Colab کلیک کنید تا `colab_runner.ipynb` باز شود.
2. سلول اول مخزن را در `/content/videorobot` کلون می‌کند (URL از مسیر Colab یا متغیر `VIDEOROBOT_REPO_URL` گرفته می‌شود).
3. سلول دوم Google Drive را Mount کرده و در صورت وجود، پوشه `MyDrive/videorobot_assets` را به `Assets/` کپی می‌کند.
4. اسکریپت `scripts/install_ffmpeg_colab.sh` اجرا می‌شود و سپس `pip install -r backend/requirements.txt` وابستگی‌ها را نصب می‌کند.
5. بک‌اند با `python -m backend.main` اجرا و سلامت آن بررسی می‌شود؛ در صورت شکست، notebook فرایند را متوقف می‌کند.
6. مانیفست نمونه نوشته، به `/render` ارسال، با `/progress/<job_id>` پیگیری و خروجی با `/download` ذخیره می‌شود.
7. سلول پایانی فرآیند را تمیز متوقف می‌کند و فایل‌ها در `/content/outputs/<job_id>/final.mp4` باقی می‌مانند.

## Next Steps for Operators
- نسخه‌های `.env` را برای بک‌اند و فرانت‌اند بسازید و فقط مقدارهای لازم را تغییر دهید؛ از commit کردن اطلاعات حساس خودداری کنید.
- با استفاده از `docs/manifest_examples/` مانیفست نمونه انتخاب یا تغییر دهید و چرخه کامل رندر را آزمایش کنید تا `inputs.sha256` و `manifest_canonical.json` تولید شوند.
- در صورت نیاز به دسترسی خارجی، `cloudflared` را نصب، `CF_TUNNEL_TOKEN` را تنظیم و اسکریپت `scripts/run_cloudflare_tunnel.sh` را در ترمینال جداگانه اجرا کنید؛ مبدا حاصل به‌طور خودکار در CORS لحاظ می‌شود.
- پس از اطمینان از صحت، می‌توانید با اجرای `make colab-badge-check` از حضور نوت‌بوک یک‌کلیکی مطمئن شوید و سپس CI را با یک Push آزمایشی فعال کنید.

## راهنمای سریع برای شما (بدون نیاز به دانش برنامه‌نویسی)
1. **نصب پیش‌نیازها:** در Colab یا لپ‌تاپ خود دستور `make setup` (یا `pip install -r backend/requirements.txt`) را اجرا کنید تا همه کتابخانه‌های لازم نصب شوند.
2. **تنظیم محیط:** فایل‌های `backend/.env.example` و `frontend/.env.example` را کپی کرده و فقط مقادیری مثل آدرس مجاز CORS یا نام تونل Cloudflare را پر کنید.
3. **راه‌اندازی سرویس:** دستور `make run` یا `python -m backend.main` را اجرا کنید؛ تا وقتی پنجره باز است سرویس فعال می‌ماند.
4. **بررسی سلامت:** `curl http://127.0.0.1:8000/healthz` را اجرا کنید؛ اگر پاسخ `{"ok": true}` بود، سرویس در دسترس است.
5. **درخواست رندر ساده:**
   ```bash
   cat docs/manifest_examples/simple_text.json > manifest.json
   curl -X POST http://127.0.0.1:8000/render \
     -H 'Content-Type: application/json' \
     -d @manifest.json
   ```
   `job_id` برگشتی را یادداشت کنید.
6. **پیگیری پیشرفت:** `curl http://127.0.0.1:8000/progress/<job_id>` را هر چند ثانیه اجرا کنید تا حالت `success` نمایش داده شود. خروجی در `outputs/<job_id>/final.mp4` (یا در Colab در `/content/outputs/...`) ذخیره می‌شود. با `curl -OJ "http://127.0.0.1:8000/download?jobId=<job_id>"` می‌توانید فایل را دانلود کنید.
7. **اشتراک‌گذاری امن:** برای دسترسی بیرونی، `cloudflared` را نصب، `CF_TUNNEL_TOKEN` را ست و `scripts/run_cloudflare_tunnel.sh` را اجرا کنید تا آدرس امن دریافت شود.
8. **امنیت:** هیچ‌گاه توکن‌ها یا رمزها را در فایل‌های پروژه commit نکنید؛ فقط در محیط خصوصی خود نگه دارید.

## Known Gaps
- فرانت‌اند همچنان تنها برای نمایش سلامت API استفاده می‌شود؛ پیاده‌سازی کنترل‌های کامل و اتصال به `/render` و `/progress` کار آینده است.
- صف رندر MoviePy تست واحد خودکار ندارد و برای پوشش کامل نیاز به تست‌های اضافی است.
- وابستگی‌های سنگین مانند `ctranslate2` ممکن است در محیط‌های محدود (CI یا CPU قدیمی) به زمان نصب بیشتری نیاز داشته باشند.

## Notes
- `/version` مقدار `VR_VERSION` و `GIT_COMMIT` را در صورت تنظیم گزارش می‌کند و در غیر این صورت از مقدار فایل `VERSION` استفاده می‌شود.
- خروجی هر job شامل `final.mp4`, `manifest_canonical.json`, `inputs.sha256`, و `report.json` است؛ از `docs/manifest_examples/` برای آزمایش سریع می‌توانید استفاده کنید.
