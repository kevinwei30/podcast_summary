#!/usr/bin/env python3
"""
podcast_summarizer.py
─────────────────────
Daily automated summarizer for 游庭皓的財經皓角.

Flow:
  1. Parse RSS feed → find today's (or latest) episode
  2. Download the audio file
  3. Transcribe with OpenAI Whisper
  4. Summarize with Claude API
  5. Deliver summary (Gmail / Slack / print to console)

Requirements:
  pip install feedparser openai anthropic requests python-dotenv

Environment variables (put in .env file):
  OPENAI_API_KEY      – for Whisper transcription
  ANTHROPIC_API_KEY   – for Claude summarization
  GMAIL_TO            – (optional) your email address
  GMAIL_FROM          – (optional) Gmail sender address
  GMAIL_APP_PASSWORD  – (optional) Gmail app password
  SLACK_WEBHOOK_URL   – (optional) Slack incoming webhook URL
"""

import os
import sys
import time
import calendar
import tempfile
import smtplib
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env is optional

# ─── CONFIG ──────────────────────────────────────────────────────────────────

RSS_FEED_URL = "https://feeds.soundcloud.com/users/soundcloud:users:735679489/sounds.rss"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
GMAIL_TO          = os.getenv("GMAIL_TO")
GMAIL_FROM        = os.getenv("GMAIL_FROM")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# How far back (in hours) to look for "today's" episode
RECENCY_HOURS = 30

# ─── STEP 1: FETCH LATEST EPISODE FROM RSS ───────────────────────────────────

def get_latest_episode(rss_url: str) -> dict | None:
    """Return the most recent episode within RECENCY_HOURS, or None."""
    print(f"📡 Fetching RSS feed: {rss_url}")
    feed = feedparser.parse(rss_url)

    if not feed.entries:
        print("❌ No episodes found in feed.")
        return None

    latest = feed.entries[0]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENCY_HOURS)

    # feedparser gives published_parsed as time.struct_time (UTC)
    pub_ts = latest.get("published_parsed")
    if pub_ts:
        pub_dt = datetime.fromtimestamp(calendar.timegm(pub_ts), tz=timezone.utc)
        if pub_dt < cutoff:
            print(f"⏰ Latest episode ({pub_dt.date()}) is older than {RECENCY_HOURS}h. Skipping.")
            return None
    else:
        pub_dt = datetime.now(timezone.utc)

    # Find audio URL
    audio_url = None
    for link in latest.get("links", []):
        if link.get("type", "").startswith("audio/"):
            audio_url = link["href"]
            break
    if not audio_url and latest.get("enclosures"):
        audio_url = latest.enclosures[0].href

    if not audio_url:
        print("❌ No audio URL found in episode.")
        return None

    return {
        "title": latest.get("title", "Unknown title"),
        "published": pub_dt.strftime("%Y-%m-%d"),
        "audio_url": audio_url,
        "description": latest.get("summary", ""),
    }


# ─── STEP 2: DOWNLOAD AUDIO ──────────────────────────────────────────────────

def download_audio(url: str, dest_path: str):
    print(f"⬇️  Downloading audio → {dest_path}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                f.write(chunk)
    size_mb = Path(dest_path).stat().st_size / 1024 / 1024
    print(f"   Done ({size_mb:.1f} MB)")


# ─── STEP 3: TRANSCRIBE WITH WHISPER ─────────────────────────────────────────

def transcribe(audio_path: str) -> str:
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    print("🎙️  Transcribing with Whisper (this may take a minute)…")
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="zh",   # Chinese – speeds up recognition
            response_format="text",
        )
    print(f"   Transcript length: {len(result)} chars")
    return result


# ─── STEP 4: SUMMARIZE WITH CLAUDE ───────────────────────────────────────────

SUMMARY_PROMPT = """\
你是一位專業的財經摘要助手。以下是今天《游庭皓的財經皓角》podcast 的逐字稿。
本集標題：{episode_title}

請用繁體中文撰寫一份清晰、有條理的摘要，包含：

1. 📌 今日重點（3-5 個 bullet points）
2. 📊 市場動態（指數、個股、商品等具體數字）
3. 💡 主持人核心觀點
4. ⚠️  需要特別關注的風險或機會

格式要易於閱讀，讓沒有時間收聽的人也能快速掌握精華。

逐字稿如下：
---
{transcript}
---
"""

def summarize(transcript: str, episode_title: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print("🤖 Summarizing with Claude…")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": SUMMARY_PROMPT.format(
                    episode_title=episode_title,
                    transcript=transcript[:50000],  # safety trim
                ),
            }
        ],
    )
    return message.content[0].text


# ─── STEP 5: DELIVER SUMMARY ─────────────────────────────────────────────────

def send_email(subject: str, body: str):
    if not all([GMAIL_FROM, GMAIL_TO, GMAIL_APP_PASSWORD]):
        print("📧 Email skipped (GMAIL_* env vars not set)")
        return
    print(f"📧 Sending email to {GMAIL_TO}…")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_FROM
    msg["To"]      = GMAIL_TO
    html_body = body.replace("\n", "<br>")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(f"<html><body style='font-family:sans-serif'>{html_body}</body></html>", "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())
    print("   Email sent ✅")


def send_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        print("💬 Slack skipped (SLACK_WEBHOOK_URL not set)")
        return
    print("💬 Sending to Slack…")
    resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    if resp.status_code == 200:
        print("   Slack sent ✅")
    else:
        print(f"   Slack delivery failed (HTTP {resp.status_code}: {resp.text})")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  財經皓角 Daily Summarizer")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. Get latest episode
    episode = get_latest_episode(RSS_FEED_URL)
    if not episode:
        print("✅ No new episode today. Exiting.")
        sys.exit(0)

    print(f"\n📻 Episode: {episode['title']}")
    print(f"   Date   : {episode['published']}")
    print(f"   Audio  : {episode['audio_url'][:80]}…")

    # 2. Download audio to a temp file
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio_path = tmp.name

    try:
        download_audio(episode["audio_url"], audio_path)

        # 3. Transcribe
        transcript = transcribe(audio_path)

        # 4. Summarize
        summary = summarize(transcript, episode["title"])

        # 5. Build output
        subject = f"📻 財經皓角摘要 {episode['published']} — {episode['title']}"
        full_output = f"{subject}\n\n{summary}"

        print("\n" + "─" * 60)
        print(full_output)
        print("─" * 60)

        # 6. Deliver
        send_email(subject, summary)
        send_slack(full_output)

        # Save locally too
        out_file = f"summary_{episode['published']}.txt"
        Path(out_file).write_text(full_output, encoding="utf-8")
        print(f"\n💾 Saved to {out_file}")

    finally:
        Path(audio_path).unlink(missing_ok=True)

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
