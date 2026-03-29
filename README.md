# 📻 財經皓角 Daily Podcast Summarizer — Setup Guide

Automates daily summaries of 游庭皓的財經皓角 via RSS → Whisper → Claude → Email/Slack.

Pipeline: **RSS feed** → **download audio** → **speed up 1.25x** → **Whisper transcription** → **Claude summary** → **Claude infographic** → **Email (with PNG) / Slack / local files**

---

## 1. Prerequisites

```bash
# Python 3.10+
python3 --version

# Install dependencies
pip install feedparser openai anthropic requests python-dotenv playwright
playwright install chromium

# ffmpeg (required for audio processing)
# macOS
brew install ffmpeg
# Windows
winget install ffmpeg
# Ubuntu/Debian
sudo apt-get install -y ffmpeg
```

---

## 2. API Keys

You need two API keys:

| Key | Purpose | Get it at |
|-----|---------|-----------|
| `OPENAI_API_KEY` | Whisper transcription | platform.openai.com |
| `ANTHROPIC_API_KEY` | Claude summarization + infographic | console.anthropic.com |

> Note: Both require billing to be set up — free tier has $0 quota.

---

## 3. Create your `.env` file

Create a file named `.env` in the same folder as the script:

```env
# Required
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Optional: Email delivery
GMAIL_FROM=yourname@gmail.com
GMAIL_TO=friend1@gmail.com,friend2@gmail.com   # comma-separated for multiple recipients
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx         # Gmail App Password (not your login password)
GMAIL_DISPLAY_NAME=財經皓角摘要                 # sender display name (default: 財經皓角摘要)

# Optional: Slack delivery
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

### How to get a Gmail App Password:
1. Go to myaccount.google.com → Security
2. Enable 2-Step Verification
3. Search "App passwords" → Create one for "Mail"
4. Paste the 16-char code into `.env`

---

## 4. Usage

### Full run (fetch → transcribe → summarize → infographic → deliver)
```bash
python podcast_summarizer.py
```

### Resume from saved transcript (skips download + Whisper)
```bash
python podcast_summarizer.py --transcript output/2026-03-27/transcript.txt
```

### Resend from saved summary (skips everything except deliver)
```bash
python podcast_summarizer.py --summary output/2026-03-27/summary.txt
```

> The infographic is only generated once per episode. If `infographic.png` already exists in the output folder, it is reused — no extra API cost.

---

## 5. Output files

Each run creates a dated folder under `output/`:

```
output/
└── 2026-03-27/
    ├── audio_fast.mp3    ← sped-up + compressed audio sent to Whisper
    ├── transcript.txt    ← raw Whisper transcript
    ├── summary.txt       ← full Claude summary (subject on line 1, body below)
    ├── infographic.png   ← 1080×1350px Instagram-ready card
    ├── infographic.html  ← source HTML for the infographic
    └── run.log           ← full console output for this run
```

---

## 6. Cost logging

After each run the script prints the actual cost for every API call:

```
   Audio duration    : 26.3 min
   Whisper cost      : $0.1578 USD

   Input tokens  : 4821
   Output tokens : 612
   Claude cost   : $0.0238 USD   ← summary

   Input tokens  : 2105
   Output tokens : 3840
   Claude cost   : $0.0643 USD   ← infographic
```

---

## 7. Schedule it daily with cron (macOS / Linux)

The podcast airs at **08:30 Taiwan time** (UTC+8). Set the cron to run at ~09:15 TW time to ensure the episode is uploaded:

```bash
# Open crontab editor
crontab -e

# Add this line (runs at 09:15 Asia/Taipei = 01:15 UTC):
15 1 * * 1-5 cd /path/to/your/script && /usr/bin/python3 podcast_summarizer.py >> /tmp/podcast_cron.log 2>&1
```

- `1-5` = Monday to Friday only
- Adjust `/path/to/your/script` to your actual folder path

### Check logs:
```bash
tail -f /tmp/podcast_cron.log
```

---

## 8. Schedule on Windows (Task Scheduler)

1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily, 09:15 (or adjust for your timezone)
3. Action: Start a program
   - Program: `python`
   - Arguments: `C:\path\to\podcast_summarizer.py`
   - Start in: `C:\path\to\script\folder`

---

## 9. Run in the cloud (free options)

If you want it to run even when your laptop is off:

### GitHub Actions (free)
Create `.github/workflows/podcast.yml`:

```yaml
name: Daily Podcast Summary
on:
  schedule:
    - cron: '15 1 * * 1-5'   # 09:15 TW time, Mon-Fri
  workflow_dispatch:           # Allow manual trigger

jobs:
  summarize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install ffmpeg
        run: sudo apt-get install -y ffmpeg
      - run: pip install feedparser openai anthropic requests python-dotenv playwright
      - run: playwright install chromium
      - run: python podcast_summarizer.py
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GMAIL_FROM: ${{ secrets.GMAIL_FROM }}
          GMAIL_TO: ${{ secrets.GMAIL_TO }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GMAIL_DISPLAY_NAME: ${{ secrets.GMAIL_DISPLAY_NAME }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

Add your keys in: GitHub repo → Settings → Secrets → Actions.

---

## 10. Estimated cost per month

With 1.25x speed-up and 48kbps compression applied before transcription:

| Item | Cost |
|------|------|
| Whisper (~26 min audio/day × 22 days) | ~$3.50 USD |
| Claude summary (~5k tokens/day × 22 days) | ~$0.50 USD |
| Claude infographic (~6k tokens/day × 22 days) | ~$1.00 USD |
| **Total** | **~$5 USD/month** |

---

## 11. Output example

```
📻 財經皓角摘要 — 2026/3/28(五)台股大跌...

1. 📌 今日重點
   • 台股因外資賣超跌破關鍵支撐...
   • 美國非農就業數據優於預期...

2. 📊 市場動態
   • 台股：-1.8%，收21,340點
   • 費半指數：-2.3%...

3. 💡 主持人核心觀點
   游庭皓認為短期修正屬健康回調...

4. ⚠️ 需要關注
   • 下週FOMC會議...
```

A 1080×1350px infographic is also generated and attached to the email.
