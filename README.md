# VideoRobot 🤖🎬

VideoRobot یک پلتفرم کامل برای ساخت ویدیوهای خودکار است که شامل موارد زیر می‌شود:

- رونویسی هوشمند صوت با Whisper و Faster-Whisper
- تولید زیرنویس متحرک و قابل شخصی‌سازی
- پردازش صوت مطابق استاندارد EBU R128
- رندر و ترکیب لایه‌های ویدیو، صدا، تصویر و متن با MoviePy و FFmpeg

## شروع سریع (Quick Links)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/englishpodcasteasy-glitch/videorobot/blob/main/VideoRobot_Colab_Runner.ipynb)

- [راهنمای کامل راه‌اندازی در REPORT.md](REPORT.md)
- [Schema مانیفست رندر](backend/schemas/render_manifest.schema.json)

## راه‌اندازی سریع در Google Colab

این مراحل در نوت‌بوک `VideoRobot_Colab_Runner.ipynb` نیز آماده شده‌اند؛ اگر ترجیح می‌دهید دستی اجرا کنید از دستورهای زیر استفاده نمایید.

1. **نصب FFmpeg (مخصوص Colab):**

   ```bash
   !bash scripts/install_ffmpeg_colab.sh
   ```

2. **نصب وابستگی‌های پایتون:**

   ```bash
   !pip install -r backend/requirements.txt
   ```

3. **تنظیم پورت و اجرای سرور:**

   ```bash
   %env BACKEND_PORT=8000
   !python backend/main.py &
   ```

4. **ساخت مانیفست نمونه** (ذخیره در `/content/manifest.json`):

   ```json
   {
     "seed": 42,
     "video": { "width": 1280, "height": 720, "fps": 30, "bg_color": "#101318" },
     "tracks": [
       { "type": "video", "src": "Assets/Intro.mp4", "start": 0, "trim_start": 0, "fit": "cover" },
       { "type": "image", "src": "Assets/Background.png", "start": 0, "duration": 7, "x": 0, "y": 0, "scale": 1.0 },
       { "type": "text",  "content": "Real Smart English", "start": 0.5, "duration": 3, "x": 60, "y": 80, "size": 64, "color": "#FFFFFF" },
       { "type": "audio", "src": "Assets/EPS7.mp3", "start": 0, "gain_db": -4 }
     ]
   }
   ```

5. **ارسال درخواست رندر:**

   ```bash
   !curl -s -X POST http://127.0.0.1:8000/render \
     -H 'Content-Type: application/json' \
     -d @/content/manifest.json
   ```

6. **پیگیری وضعیت:**

   ```bash
   !curl -s http://127.0.0.1:8000/progress/<job_id>
   ```

7. **دریافت فایل خروجی:**

   ```bash
   !curl -s -OJ "http://127.0.0.1:8000/download?jobId=<job_id>"
   ```

خروجی‌های MP4 در مسیر `/content/outputs/<job_id>/final.mp4` (یا در اجراهای محلی `./outputs/<job_id>/final.mp4`) ذخیره می‌شوند. در هر پوشه شغل فایل‌های `manifest_canonical.json`, `inputs.sha256` و `report.json` نیز ذخیره شده‌اند تا اجرای مجدد همان مانیفست نتایج کاملاً تکرارپذیر ایجاد کند.

## راه‌اندازی محلی (Local Run)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
python backend/main.py
```

سپس از طریق `http://127.0.0.1:8000/healthz` سلامت سرویس را بررسی کنید و از نمونه دستورات بالا برای ارسال درخواست‌های رندر استفاده نمایید.
