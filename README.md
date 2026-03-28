# 📻 財經皓角 Daily Podcast Summarizer — Setup Guide

Automates daily summaries of 游庭皓的財經皓角 via RSS → Whisper → Claude → Email/Slack.

---

## 1. Prerequisites

```bash
# Python 3.10+
python3 --version

# Install dependencies
pip install feedparser openai anthropic requests python-dotenv
```

---

## 2. API Keys

You need two API keys:

| Key | Purpose | Get it at |
|-----|---------|-----------|
| `OPENAI_API_KEY` | Whisper transcription (~NT$0.5/episode) | platform.openai.com |
| `ANTHROPIC_API_KEY` | Claude summarization (~NT$0.3/episode) | console.anthropic.com |

---

## 3. Create your `.env` file

Create a file named `.env` in the same folder as the script:

```env
# Required
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Optional: Email delivery
GMAIL_FROM=yourname@gmail.com
GMAIL_TO=yourname@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   # Gmail App Password (not your login password)

# Optional: Slack delivery
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

### How to get a Gmail App Password:
1. Go to myaccount.google.com → Security
2. Enable 2-Step Verification
3. Search "App passwords" → Create one for "Mail"
4. Paste the 16-char code into `.env`

---

## 4. Test it manually

```bash
python3 podcast_summarizer.py
```

It will print the summary to your terminal and send it to email/Slack if configured.

---

## 5. Schedule it daily with cron (macOS / Linux)

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

## 6. Schedule on Windows (Task Scheduler)

1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily, 09:15 (or adjust for your timezone)
3. Action: Start a program
   - Program: `python`
   - Arguments: `C:\path\to\podcast_summarizer.py`
   - Start in: `C:\path\to\script\folder`

---

## 7. Run in the cloud (free options)

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
      - run: pip install feedparser openai anthropic requests python-dotenv
      - run: python podcast_summarizer.py
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GMAIL_FROM: ${{ secrets.GMAIL_FROM }}
          GMAIL_TO: ${{ secrets.GMAIL_TO }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

Add your keys in: GitHub repo → Settings → Secrets → Actions.

---

## 8. Estimated cost per month

| Item | Cost |
|------|------|
| Whisper (~30 min audio/day × 22 days) | ~$1.50 USD |
| Claude API (1500 tokens × 22 days) | ~$0.50 USD |
| **Total** | **~$2 USD/month** |

---

## 9. Output example

```
📻 財經皓角摘要 2026-03-28 — 2026/3/28(五)台股大跌...

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
