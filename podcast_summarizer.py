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
  pip install feedparser openai anthropic requests python-dotenv playwright
  playwright install chromium

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
from email.mime.image import MIMEImage
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
PTT_ID             = os.getenv("PTT_ID")
PTT_PASSWORD       = os.getenv("PTT_PASSWORD")
PTT_BOARD          = os.getenv("PTT_BOARD", "Stock")  # default board

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
    return result, cost_usd


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
    return message.content[0].text, cost_usd


# ─── STEP 5: GENERATE INFOGRAPHIC ────────────────────────────────────────────

INFOGRAPHIC_PROMPT = """\
你是一位專業的網頁設計師。請根據以下財經podcast摘要，生成一個適合 Instagram 發布的單頁資訊圖表 HTML。

設計規格：
- 尺寸：1080×1350px（Instagram 直式比例）
- 風格：深色金融主題（深藍/深灰背景，金色/白色文字）
- 字型：使用 Google Fonts Noto Sans TC（支援繁體中文）
- 版面：由上至下分為以下區塊

版面結構：
1. 頂部 Header：「財經皓角」標題 + 集數標題（較小字）+ 日期
2. 📌 今日重點：3-5 個重點 bullet points
3. 📊 市場動態：指數、個股等數據（漲用綠色，跌用紅色）
4. 💡 核心觀點：主持人觀點 1-2 句
5. ⚠️ 風險關注：1-2 個需注意事項
6. 底部 Footer：「游庭皓的財經皓角」小字

技術要求：
- 完整的 HTML 文件，包含所有 CSS（inline 或 <style> 標籤）
- 使用 @import 載入 Google Fonts
- 固定寬度 1080px，高度 1350px，overflow: hidden
- CSS 請保持簡潔，避免過多裝飾性元素，以確保內容完整輸出
- 只回傳 HTML 程式碼，不要加任何說明文字

摘要內容：
---
{summary}
---

集數標題：{episode_title}
日期：{date_str}
"""

def generate_infographic(summary: str, episode_title: str, date_str: str, out_dir: Path) -> Path:
    import anthropic
    from playwright.sync_api import sync_playwright

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print("🎨 Generating infographic HTML with Claude…")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        messages=[{
            "role": "user",
            "content": INFOGRAPHIC_PROMPT.format(
                summary=summary,
                episode_title=episode_title,
                date_str=date_str,
            ),
        }],
    )
    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost_usd = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)
    print(f"   Input tokens  : {input_tokens}")
    print(f"   Output tokens : {output_tokens}")
    print(f"   Claude cost   : ${cost_usd:.4f} USD")
    html = message.content[0].text.strip()
    # Strip markdown code fences if Claude wrapped the HTML
    if html.startswith("```"):
        html = html.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    html_path = out_dir / "infographic.html"
    html_path.write_text(html, encoding="utf-8")

    print("📸 Rendering infographic with Playwright…")
    png_path = out_dir / "infographic.png"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350})
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        browser.close()

    size_kb = png_path.stat().st_size / 1024
    print(f"   Saved → {png_path} ({size_kb:.0f} KB)")
    return png_path, cost_usd


# ─── STEP 5: DELIVER SUMMARY ─────────────────────────────────────────────────

def send_email(subject: str, body: str, image_path: Path = None):
    if not all([GMAIL_FROM, GMAIL_TO, GMAIL_APP_PASSWORD]):
        print("📧 Email skipped (GMAIL_* env vars not set)")
        return
    recipients = [r.strip() for r in GMAIL_TO.split(",")]
    print(f"📧 Sending email to {', '.join(recipients)}…")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = f"{GMAIL_DISPLAY_NAME} <{GMAIL_FROM}>"
    msg["To"]      = ", ".join(recipients)
    html_body = body.replace("\n", "<br>")
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body, "plain", "utf-8"))
    body_part.attach(MIMEText(f"<html><body style='font-family:sans-serif'>{html_body}</body></html>", "html", "utf-8"))
    msg.attach(body_part)
    if image_path and image_path.exists():
        with open(image_path, "rb") as f:
            img = MIMEImage(f.read(), name=image_path.name)
        msg.attach(img)
        print(f"   Attached → {image_path.name}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_FROM, recipients, msg.as_string())
    print("   Email sent ✅")


def send_ptt(title: str, content: str):
    if not all([PTT_ID, PTT_PASSWORD]):
        print("📋 PTT skipped (PTT_ID / PTT_PASSWORD not set)")
        return
    try:
        import PyPTT
    except ImportError:
        print("📋 PTT skipped (PyPTT not installed)")
        return
    print(f"📋 Posting to PTT/{PTT_BOARD}…")
    try:
        bot = PyPTT.API()
        bot.login(PTT_ID, PTT_PASSWORD, kick_other_login=True)
        bot.post(
            board=PTT_BOARD,
            title=title,
            content=content,
            sign_file=PyPTT.data_type.SignType.NoSigned,
        )
        bot.logout()
        print("   PTT post sent ✅")
    except Exception as e:
        print(f"   PTT post failed: {e}")


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
    parser.add_argument("--verbose", action="store_true", help="Print full summary to console (useful for CI logs)")
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

    cost_transcribe = 0.0
    cost_summarize  = 0.0
    cost_infographic = 0.0

    # ── Stage 1: resolve transcript, summary, episode metadata ──────────────
    if args.summary:
        summary_path = Path(args.summary)
        out_dir = summary_path.parent
        full_output = summary_path.read_text(encoding="utf-8")
        subject, summary = full_output.split("\n", 1)
        subject = subject.strip()
        summary = summary.strip()
        episode_title = subject.split(" — ", 1)[-1].strip() if " — " in subject else out_dir.name
        date_str = out_dir.name
        print(f"\n📄 Loaded summary from {summary_path}")

    elif args.transcript:
        transcript_path = Path(args.transcript)
        out_dir = transcript_path.parent
        date_str = out_dir.name
        transcript = transcript_path.read_text(encoding="utf-8")
        existing_summary = out_dir / "summary.txt"
        if existing_summary.exists():
            first_line = existing_summary.read_text(encoding="utf-8").split("\n", 1)[0]
            episode_title = first_line.split(" — ", 1)[-1].strip() if " — " in first_line else date_str
        else:
            episode_title = date_str
        print(f"\n📄 Loaded transcript from {transcript_path} ({len(transcript)} chars)")
        summary = None  # will be generated below

    else:
        episode = get_latest_episode(RSS_FEED_URL)
        if not episode:
            print("✅ No new episode today. Exiting.")
            tee.close()
            sys.exit(0)
        date_str = episode["published"]
        episode_title = episode["title"]
        out_dir = Path(f"output/{date_str}")
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n📻 Episode : {episode_title}")
        print(f"   Date    : {date_str}")
        print(f"   Audio   : {episode['audio_url'][:80]}…")
        print(f"\n📁 Output folder: {out_dir}")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            audio_path = tmp.name
        try:
            download_audio(episode["audio_url"], audio_path)
            fast_path = speed_up_audio(audio_path)
            audio_out = out_dir / "audio_fast.mp3"
            Path(fast_path).rename(audio_out)
            print(f"   Saved → {audio_out}")
            transcript, cost_transcribe = transcribe(str(audio_out))
            transcript_out = out_dir / "transcript.txt"
            transcript_out.write_text(transcript, encoding="utf-8")
            print(f"   Saved → {transcript_out}")
        finally:
            Path(audio_path).unlink(missing_ok=True)
        summary = None  # will be generated below

    # ── Stage 2: summarize (skipped when resuming from --summary) ────────────
    if summary is None:
        summary, cost_summarize = summarize(transcript, episode_title)
        subject = f"📻 財經皓角摘要 — {episode_title}"
        full_output = f"{subject}\n\n{summary}"
        summary_out = out_dir / "summary.txt"
        summary_out.write_text(full_output, encoding="utf-8")
        print(f"\n💾 Saved → {summary_out}")

    print("\n" + "─" * 60)
    if args.verbose:
        print(full_output)
    else:
        print("\n".join(full_output.splitlines()[:10]))
        print("…  (full summary saved to summary.txt)")
    print("─" * 60)

    # ── Stage 3: infographic ─────────────────────────────────────────────────
    if (out_dir / "infographic.png").exists():
        print("🎨 Infographic already exists, skipping generation.")
    else:
        _, cost_infographic = generate_infographic(summary, episode_title, date_str, out_dir)

    # ── Stage 4: deliver ─────────────────────────────────────────────────────
    send_email(subject, summary, image_path=out_dir / "infographic.png")
    send_slack(full_output)
    ptt_title = f"[情報] 財經皓角每日摘要 {date_str} — {episode_title}"
    ptt_content = f"{summary}\n\n--\n本文由自動化程式整理自《游庭皓的財經皓角》Podcast"
    send_ptt(ptt_title, ptt_content)

    total_cost = cost_transcribe + cost_summarize + cost_infographic
    print("\n" + "─" * 60)
    print("💰 Cost Summary")
    print(f"   Transcribe   : ${cost_transcribe:.4f} USD")
    print(f"   Summarize    : ${cost_summarize:.4f} USD")
    print(f"   Infographic  : ${cost_infographic:.4f} USD")
    print(f"   ─────────────────────────")
    print(f"   Total        : ${total_cost:.4f} USD")
    print("─" * 60)

    print("\n✅ Done!")
    tee.close(final_path=out_dir / "run.log")
    print(f"📋 Log saved → {out_dir / 'run.log'}")


if __name__ == "__main__":
    main()
