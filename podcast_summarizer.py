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
import argparse
import tempfile
import subprocess
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

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
GMAIL_TO           = os.getenv("GMAIL_TO")           # comma-separated for multiple recipients
GMAIL_FROM         = os.getenv("GMAIL_FROM")          # Gmail address used to authenticate
GMAIL_DISPLAY_NAME = os.getenv("GMAIL_DISPLAY_NAME", "財經皓角摘要")  # sender display name
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
SLACK_WEBHOOK_URL  = os.getenv("SLACK_WEBHOOK_URL")

# How far back (in hours) to look for "today's" episode
RECENCY_HOURS = 60

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


# ─── STEP 2b: SPEED UP AUDIO ─────────────────────────────────────────────────

AUDIO_SPEED = 1.25  # speeds up audio to reduce Whisper cost

def speed_up_audio(input_path: str) -> str:
    """Return path to a sped-up copy of the audio file using ffmpeg."""
    output_path = input_path.replace(".mp3", "_fast.mp3")
    print(f"⏩ Speeding up audio {AUDIO_SPEED}x with ffmpeg…")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-filter:a", f"atempo={AUDIO_SPEED}",
            "-b:a", "48k",  # reduce bitrate to keep file under 25MB limit
            "-vn", output_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"   Done ({size_mb:.1f} MB)")
    return output_path


# ─── STEP 3: TRANSCRIBE WITH WHISPER ─────────────────────────────────────────

def get_audio_duration_seconds(audio_path: str) -> float:
    """Return audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


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
    duration_sec = get_audio_duration_seconds(audio_path)
    duration_min = duration_sec / 60
    cost_usd = (duration_sec / 60) * 0.006
    print(f"   Transcript length : {len(result)} chars")
    print(f"   Audio duration    : {duration_min:.1f} min")
    print(f"   Whisper cost      : ${cost_usd:.4f} USD")
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
        max_tokens=4096,
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
    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost_usd = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)
    print(f"   Input tokens  : {input_tokens}")
    print(f"   Output tokens : {output_tokens}")
    print(f"   Claude cost   : ${cost_usd:.4f} USD")
    return message.content[0].text


# ─── STEP 5: DELIVER SUMMARY ─────────────────────────────────────────────────

def send_email(subject: str, body: str):
    if not all([GMAIL_FROM, GMAIL_TO, GMAIL_APP_PASSWORD]):
        print("📧 Email skipped (GMAIL_* env vars not set)")
        return
    recipients = [r.strip() for r in GMAIL_TO.split(",")]
    print(f"📧 Sending email to {', '.join(recipients)}…")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{GMAIL_DISPLAY_NAME} <{GMAIL_FROM}>"
    msg["To"]      = ", ".join(recipients)
    html_body = body.replace("\n", "<br>")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(f"<html><body style='font-family:sans-serif'>{html_body}</body></html>", "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_FROM, recipients, msg.as_string())
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


# ─── LOGGING ─────────────────────────────────────────────────────────────────

class Tee:
    """Write to both stdout and a log file simultaneously."""
    def __init__(self, log_path: Path):
        self._stdout = sys.stdout
        self._file = log_path.open("w", encoding="utf-8")
        sys.stdout = self

    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self, final_path: Path = None):
        sys.stdout = self._stdout
        self._file.close()
        if final_path and final_path != Path(self._file.name):
            final_path.unlink(missing_ok=True)
            Path(self._file.name).rename(final_path)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", help="Path to existing transcript.txt to skip download/transcription")
    parser.add_argument("--summary", help="Path to existing summary.txt to skip everything and just deliver")
    args = parser.parse_args()

    # Start logging — write to a temp file until we know the episode output folder
    Path("output").mkdir(exist_ok=True)
    run_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    temp_log = Path(f"output/run_{run_ts}.log")
    tee = Tee(temp_log)

    print("=" * 60)
    print("  財經皓角 Daily Summarizer")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if args.summary:
        # Deliver from existing summary — skip everything else
        summary_path = Path(args.summary)
        full_output = summary_path.read_text(encoding="utf-8")
        # First line is the subject, rest is the body
        lines = full_output.split("\n", 1)
        subject = lines[0].strip()
        summary = lines[1].strip() if len(lines) > 1 else full_output
        out_dir = summary_path.parent
        print(f"\n📄 Loaded summary from {summary_path}")
        print("\n" + "─" * 60)
        print(full_output)
        print("─" * 60)
        send_email(subject, summary)
        send_slack(full_output)
        print("\n✅ Done!")
        tee.close(final_path=out_dir / "run.log")
        return

    if args.transcript:
        # Resume from existing transcript

        transcript_path = Path(args.transcript)
        transcript = transcript_path.read_text(encoding="utf-8")
        out_dir = transcript_path.parent
        date_str = out_dir.name
        # Try to recover episode title from existing summary.txt
        existing_summary = out_dir / "summary.txt"
        if existing_summary.exists():
            first_line = existing_summary.read_text(encoding="utf-8").split("\n", 1)[0]
            # Subject format: "📻 財經皓角摘要 YYYY-MM-DD — <title>"
            episode_title = first_line.split(" — ", 1)[-1].strip() if " — " in first_line else date_str
        else:
            episode_title = date_str
        print(f"\n📄 Loaded transcript from {transcript_path} ({len(transcript)} chars)")
    else:
        # 1. Get latest episode
        episode = get_latest_episode(RSS_FEED_URL)
        if not episode:
            print("✅ No new episode today. Exiting.")
            tee.close()
            sys.exit(0)

        print(f"\n📻 Episode: {episode['title']}")
        print(f"   Date   : {episode['published']}")
        print(f"   Audio  : {episode['audio_url'][:80]}…")

        # Create output folder for this episode
        out_dir = Path(f"output/{episode['published']}")
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n📁 Output folder: {out_dir}")

        # 2. Download audio to a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            audio_path = tmp.name

        fast_path = None
        try:
            download_audio(episode["audio_url"], audio_path)

            # 2b. Speed up audio — save to output folder
            fast_path = speed_up_audio(audio_path)
            audio_out = out_dir / "audio_fast.mp3"
            Path(fast_path).rename(audio_out)
            fast_path = str(audio_out)
            print(f"   Saved → {audio_out}")

            # 3. Transcribe — save transcript
            transcript = transcribe(fast_path)
            transcript_out = out_dir / "transcript.txt"
            transcript_out.write_text(transcript, encoding="utf-8")
            print(f"   Saved → {transcript_out}")

        finally:
            Path(audio_path).unlink(missing_ok=True)

        date_str = episode["published"]
        episode_title = episode["title"]

    # 4. Summarize
    summary = summarize(transcript, episode_title)

    # 5. Build output
    subject = f"📻 財經皓角摘要 — {episode_title}"
    full_output = f"{subject}\n\n{summary}"

    print("\n" + "─" * 60)
    print(full_output)
    print("─" * 60)

    # 6. Deliver
    send_email(subject, summary)
    send_slack(full_output)

    # Save summary to output folder
    summary_out = out_dir / "summary.txt"
    summary_out.write_text(full_output, encoding="utf-8")
    print(f"\n💾 Saved → {summary_out}")

    print("\n✅ Done!")

    tee.close(final_path=out_dir / "run.log")
    print(f"📋 Log saved → {out_dir / 'run.log'}")


if __name__ == "__main__":
    main()
