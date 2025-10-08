# VideoRobot 🤖🎬

VideoRobot یک پلتفرم کامل برای ساخت ویدیوهای خودکار با تمرکز بر Colab GPU است. این مخزن شامل بک‌اند Flask با صف رندر MoviePy، سرویس رندر قطعی، اسکریپت‌های Cloudflare Tunnel، فرانت‌اند استاتیک برای آزمایش سلامت API و اسناد کامل بهره‌برداری است.

## Quick Links

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/englishpodcasteasy-glitch/videorobot/blob/main/colab_runner.ipynb)

- [راهنمای کامل راه‌اندازی و ممیزی](REPORT.md)
- [Schema کامل مانیفست رندر](backend/schemas/render_manifest.schema.json)
- [نمونه مانیفست‌ها](docs/manifest_examples/)
- [نوت‌بوک‌های جانبی](notebooks/)

## Project Overview

- **Deterministic Rendering:** `backend/renderer.py` برای هر job یک خروجی ثابت تولید می‌کند؛ با seed ثابت و دارایی یکسان، همیشه همان `inputs.sha256`، مدت‌زمان و لایه‌بندی حاصل می‌شود.
- **امنیت و Hygiene:** پاسخ‌ها به‌صورت `{ok,data,error}`، CORS محدود به مبداهای امن، و `.env.example`‌ها در هر دو بخش در دسترس است. هیچ توکن یا میزبان سخت‌کدی باقی نمانده است.
- **کارتابل Colab:** نوت‌بوک `colab_runner.ipynb` کل فرآیند نصب FFmpeg، کلون مخزن، راه‌اندازی بک‌اند، ارسال job نمونه، مانیتورینگ و دانلود خروجی را خودکار می‌کند و Mount کردن Google Drive را هم پوشش می‌دهد.
- **فرانت‌اند مینیمال:** `frontend/main.js` وضعیت سلامت بک‌اند را از `/healthz` خوانده و در ناوبری نشان می‌دهد؛ فقط از `VITE_API_BASE_URL` یا آدرس پیش‌فرض برای تماس استفاده می‌شود.
- **CI & Release:** GitHub Actions (پرونده‌های `ci.yml` و `release.yml`) نصب وابستگی‌ها، اجرای `pre-commit` و تولید آرتیفکت‌های انتشار شامل گزارش، نوت‌بوک و مثال‌ها را تضمین می‌کنند.

## Renderer Manifest Schema Snapshot

```json
{
  "type": "object",
  "required": ["video", "tracks"],
  "properties": {
    "seed": {"type": "integer"},
    "video": {"type": "object", "properties": {"width": {"type": "integer"}, "height": {"type": "integer"}, "fps": {"type": "number"}, "bg_color": {"type": "string"}}},
    "tracks": {
      "type": "array",
      "items": {
        "oneOf": [
          {"$ref": "#/definitions/videoTrack"},
          {"$ref": "#/definitions/audioTrack"},
          {"$ref": "#/definitions/imageTrack"},
          {"$ref": "#/definitions/textTrack"}
        ]
      }
    }
  }
}
```

جزئیات کامل را در [`backend/schemas/render_manifest.schema.json`](backend/schemas/render_manifest.schema.json) ببینید یا از نمونه‌های آماده در [`docs/manifest_examples/`](docs/manifest_examples/) استفاده کنید.

## Curl Examples

ارسال job جدید:

```bash
curl -s -X POST "${VITE_API_BASE_URL:-http://127.0.0.1:8000}/render" \
  -H "Content-Type: application/json" \
  -d @docs/manifest_examples/simple_text.json
```

پیگیری وضعیت:

```bash
curl -s "${VITE_API_BASE_URL:-http://127.0.0.1:8000}/progress/<job_id>"
```

دانلود خروجی:

```bash
curl -s -OJ "${VITE_API_BASE_URL:-http://127.0.0.1:8000}/download?jobId=<job_id>"
```

## Colab GPU Quickstart

1. روی نشان «Open in Colab» بالا کلیک کنید تا `colab_runner.ipynb` باز شود.
2. سلول کلون مخزن مسیر GitHub را به‌طور خودکار از URL Colab استخراج می‌کند (در صورت نیاز می‌توانید `VIDEOROBOT_REPO_URL` را قبل از اجرا تغییر دهید).
3. سلول دوم Google Drive را Mount می‌کند؛ در صورت داشتن پوشه `MyDrive/videorobot_assets` فایل‌ها به `Assets/` منتقل می‌شوند.
4. اسکریپت `scripts/install_ffmpeg_colab.sh` FFmpeg را نصب یا تأیید می‌کند.
5. `pip install -r backend/requirements.txt` وابستگی‌های دقیقاً pin شده را نصب می‌کند.
6. بک‌اند با `python -m backend.main` در پس‌زمینه اجرا می‌شود و `/healthz` بررسی می‌گردد.
7. مانیفست نمونه ساخته، به `/render` ارسال، و با `/progress/<job_id>` پیگیری می‌شود.
8. خروجی MP4 از `/download` گرفته و در `/content/outputs/<job_id>/final.mp4` ذخیره می‌شود.
9. سلول آخر فرایند را تمیز متوقف می‌کند.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
make setup          # نصب وابستگی‌ها + pre-commit
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
make run            # اجرای بک‌اند روی BACKEND_PORT
```

- از `make test` برای `python -m compileall backend`، و از `make lint` یا `make format` برای اجرای هوک‌های `pre-commit` استفاده کنید.
- متغیرهای `BACKEND_PORT`, `CORS_ALLOW_ORIGIN`, `CF_TUNNEL_HOSTNAME`, `VR_VERSION` و `GIT_COMMIT` در `.env` بک‌اند در دسترس هستند؛ `/version` مقدار `VR_VERSION` یا مقدار خوانده‌شده از فایل `VERSION` را برمی‌گرداند.
- برای فرانت‌اند استاتیک، در فایل `frontend/.env` مقدار `VITE_API_BASE_URL` را تنظیم و سپس با یک سرور ساده (`python -m http.server frontend`) صفحات را سرو کنید.

## Frontend Health Badge

در ناوبری صفحه اصلی عنصر کوچکی با شناسه `api-status` وجود دارد که پس از بارگذاری صفحه با استفاده از `fetch` به مسیر `/healthz` متصل می‌شود. اگر پاسخ موفق باشد برچسب سبز «API: Online» نمایش داده می‌شود؛ در غیر این صورت پیام «API: Offline» با کلاس قرمز ظاهر خواهد شد. مبنای URL از یکی از متغیرهای سراسری زیر خوانده می‌شود:

```javascript
window.VIDEOROBOT_API_BASE_URL || window.VITE_API_BASE_URL || window.API_BASE_URL || 'http://127.0.0.1:8000'
```

می‌توانید این مقدار را قبل از لود `main.js` در صفحه تنظیم کنید، یا فایل `frontend/.env` را برای ابزارهای build آینده به‌روزرسانی نمایید.

## Troubleshooting

- **وابستگی‌های سنگین:** `ctranslate2` و `faster-whisper` روی CPUهای بدون AVX کند هستند؛ برای اجرا روی سیستم‌های ضعیف می‌توانید مدل‌های کوچک‌تر انتخاب کنید.
- **FFmpeg در Colab:** اگر اسکریپت نصب به‌دلیل محدودیت apt شکست خورد، runtime را Restart کنید و دوباره سلول را اجرا نمایید.
- **Cloudflare Tunnel:** پس از نصب `cloudflared` و تنظیم `CF_TUNNEL_TOKEN`، اسکریپت `scripts/run_cloudflare_tunnel.sh` به‌طور خودکار مبدا جدید را به CORS اضافه می‌کند.
- **فرانت‌اند بدون API:** اگر سرویس بک‌اند در دسترس نباشد، برچسب وضعیت «Offline» می‌ماند و در کنسول مرورگر خطا ثبت می‌شود؛ URL را بررسی و مجدداً تلاش کنید.

## نسخه‌بندی

- نسخه فعلی پروژه: محتوای فایل [`VERSION`](VERSION) (به‌صورت پیش‌فرض `0.1.0`).
- متغیرهای محیطی `VR_VERSION` و `GIT_COMMIT` هنگام راه‌اندازی برای گزارش نسخه استفاده می‌شوند و در `/version` قابل مشاهده هستند.
