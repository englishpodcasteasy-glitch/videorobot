# 🎬 VideoRobot 🤖 — Full Auto Video Rendering on Google Colab

VideoRobot یک پلتفرم کاملاً خودکار برای ساخت ویدیو با استفاده از **Google Colab GPU** است.  
این سیستم ترکیبی از Flask Backend، MoviePy Renderer، رابط کاربری Gradio و پشتیبانی از Google Drive است.  
فقط با یک کلیک می‌توانید از صفر تا خروجی MP4 را بسازید.

---

## ⚡ Quick Launch

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/englishpodcasteasy-glitch/videorobot/blob/main/colab_runner.ipynb)

---

## 🧠 Features

- ✅ **Backend:** Flask + MoviePy queue renderer  
- ✅ **Frontend:** Gradio UI (modern & minimal)  
- ✅ **Storage:** Google Drive Integration  
- ✅ **Rendering:** Deterministic (identical output every time)  
- ✅ **Tunnel:** Cloudflare public URL ready  
- ✅ **Aspect Ratios:** 16:9 / 9:16 / 1:1  
- ✅ **Font Selector:** Choose any `.ttf` or `.otf`  
- ✅ **Audio & BGM Control:** Volume, ducking, VAD, LUFS normalization  

---

## 🧩 Repository Structure

```
videorobot/
├── backend/
│   ├── main.py
│   ├── renderer.py
│   ├── renderer_service.py
│   ├── audio_processor.py
│   ├── scheduler.py
│   ├── subtitles.py
│   ├── utils.py
│   └── config.py
├── frontend/
│   └── index.html
├── scripts/
│   └── install_ffmpeg_colab.sh
├── Assets/
│   ├── Intro.mp4
│   ├── Outro.mp4
│   ├── Background.png
│   ├── CTA.mp4
│   ├── Music.mp3
│   └── Inter_18pt-ExtraBold.ttf
├── colab_runner.ipynb
└── README.md
```

---

## 🚀 Colab GPU Render Quickstart

### 1️⃣ نصب و آماده‌سازی محیط
```bash
!apt-get -qq update && apt-get -qq -y install ffmpeg
!pip install -q "moviepy>=1.0.3,<3" "imageio-ffmpeg>=0.4.9,<1" flask flask-cors gradio requests
```

### 2️⃣ تنظیم پورت و متغیرها
```bash
%env BACKEND_PORT=8000
%env SDL_AUDIODRIVER=dummy
%env XDG_RUNTIME_DIR=/tmp
```

### 3️⃣ اجرای بک‌اند
```bash
!python -m backend.main &
```

---

## 🧾 Manifest نمونه (ذخیره در `/content/manifest.json`)
```json
{
  "seed": 42,
  "video": { "width": 1080, "height": 1920, "fps": 30, "bg_color": "#000000" },
  "tracks": [
    { "type": "video", "src": "Assets/Intro.mp4", "start": 0, "fit": "cover" },
    { "type": "image", "src": "Assets/Background.png", "start": 0, "duration": 6, "fit": "cover" },
    { "type": "text",  "content": "Real Smart English", "start": 0.5, "duration": 3.5, "x": 60, "y": 80, "size": 72, "color": "#FFD700" },
    { "type": "audio", "src": "Assets/EPS7.mp3", "start": 0, "gain_db": -4 },
    { "type": "video", "src": "Assets/CTA.mp4", "start": 12, "fit": "cover" },
    { "type": "video", "src": "Assets/Outro.mp4", "start": 15, "fit": "cover" }
  ],
  "config": {
    "aspectRatio": "9:16",
    "captions": {
      "fontFamily": "Inter_18pt-ExtraBold.ttf",
      "fontSize": 80,
      "primaryColor": "#FFFFFF",
      "highlightColor": "#FFD700",
      "position": "Bottom",
      "marginV": 70
    },
    "audio": { "useVAD": true, "targetLufs": -16.0 },
    "bgm": { "path": "Assets/Music.mp3", "gain_db": -8, "ducking": true }
  }
}
```

---

## 🎬 اجرای Render Job
```bash
!curl -s -X POST http://127.0.0.1:8000/render \
  -H 'Content-Type: application/json' \
  -d @/content/manifest.json
```

---

## 📊 بررسی وضعیت Render
```bash
!curl -s http://127.0.0.1:8000/progress/<job_id>
```

---

## 📥 دانلود ویدیو نهایی
```bash
!curl -s -OJ "http://127.0.0.1:8000/download?jobId=<job_id>"
```

> خروجی در مسیر زیر ذخیره می‌شود:
> `/content/outputs/<job_id>/final.mp4` یا  
> `/content/drive/MyDrive/VideoRobot/Output/<job_id>.mp4`

---

## 🧠 رابط کاربری Gradio (در Colab Notebook)
- انتخاب فایل صوتی، ویدیو، اینترو، اوترو و CTA  
- تنظیم فونت از پوشه‌ی Assets  
- انتخاب نسبت تصویر (16:9 / 9:16 / 1:1)  
- کنترل صدا و Ducking موسیقی  
- ساخت مانیفست و رندر با یک کلیک  
- دانلود مستقیم MP4  

🎯 اجرای رابط کاربری در Colab:
[Open in Colab → colab_runner.ipynb](https://colab.research.google.com/github/englishpodcasteasy-glitch/videorobot/blob/main/colab_runner.ipynb)

---

## 🧩 API Summary

| Endpoint | Method | Description |
|-----------|---------|-------------|
| `/render` | POST | شروع فرآیند رندر |
| `/progress/<job_id>` | GET | دریافت وضعیت فعلی |
| `/download?jobId=<job_id>` | GET | دانلود MP4 نهایی |

---

## ⚙️ Cloudflare Tunnel (اختیاری)
```bash
!bash run_cloudflare_tunnel.sh
```

خروجی مثلاً:
```
https://videorobot-demo.trycloudflare.com
```

---

## 🩺 Troubleshooting

| مشکل | علت | راه‌حل |
|-------|------|--------|
| ❌ ModuleNotFoundError | اجرای محلی ناقص | `python -m backend.main` |
| 🔇 خطای ALSA | محیط Colab بدون صداست | `%env SDL_AUDIODRIVER=dummy` |
| ⚠️ پورت مشغول است | پورت را تغییر بده | `%env BACKEND_PORT=8001` |
| 🧩 فونت پیدا نشد | فونت را در Assets قرار بده | `Inter_18pt-ExtraBold.ttf` |
| ⛔ خروجی دانلود نشد | خروجی در `/content/outputs` است | مسیر را بررسی کن |

---

## 🧬 ویژگی‌های کلیدی

✅ **Deterministic Rendering** — خروجی همیشه یکسان  
✅ **GPU Optimized** — مخصوص Colab GPU  
✅ **Drive Integration** — هماهنگ با Google Drive  
✅ **Modern Gradio UI** — زیبا و ساده  
✅ **Self-contained Notebook** — اجرا بدون وابستگی

---

## 📜 License

MIT License © 2025 Real Smart English — All Rights Reserved.

---

## 💬 پایان

VideoRobot به شما اجازه می‌دهد ویدیوهای آموزشی، پادکست و Shorts را  
در Colab با کیفیت بالا و کاملاً خودکار بسازید.  
🎥 اجرای هوشمند، سریع و تمیز — مخصوص خالقان حرفه‌ای محتوا.
