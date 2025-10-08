# VideoRobot 🤖🎬

VideoRobot یک پلتفرم کامل برای ساخت ویدیوهای خودکار با تمرکز بر Colab GPU است. این مخزن شامل بک‌اند Flask با صف رندر MoviePy، سرویس رندر قطعی، اسکریپت‌های Cloudflare Tunnel، فرانت‌اند استاتیک برای آزمایش سلامت API و اسناد کامل بهره‌برداری است.

## Quick Links

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/englishpodcasteasy-glitch/videorobot/blob/main/colab_runner.ipynb)

## Colab GPU Render Quickstart

1. **Install FFmpeg (Colab-friendly):** `!bash scripts/install_ffmpeg_colab.sh`
2. **Install Python dependencies:** `!pip install -r backend/requirements.txt`
3. **Expose the backend port:** `%env BACKEND_PORT=8000`
4. **Launch the server:** `!python backend/main.py &`
5. **Prepare a manifest** (save as `/content/manifest.json` for the curl commands below):

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

6. **Submit a render job:**

   ```bash
   !curl -s -X POST http://127.0.0.1:8000/render \
     -H 'Content-Type: application/json' \
     -d @/content/manifest.json
   ```

7. **Track progress:** `!curl -s http://127.0.0.1:8000/progress/<job_id>`

8. **Download the result:** `!curl -s -OJ "http://127.0.0.1:8000/download?jobId=<job_id>"`

Rendered MP4 files live under `/content/outputs/<job_id>/final.mp4` on Colab (or `./outputs/<job_id>/final.mp4` locally). Each job directory also contains `manifest_canonical.json`, `inputs.sha256`, and `report.json`, allowing you to reproduce results deterministically: rerunning the same manifest yields identical hashes and track layouts.
