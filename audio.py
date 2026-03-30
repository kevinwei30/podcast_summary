import calendar
import subprocess
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import RSS_FEED_URL, RECENCY_HOURS, AUDIO_SPEED, OPENAI_API_KEY


def get_latest_episode(rss_url: str) -> dict | None:
    """Return the most recent episode within RECENCY_HOURS, or None."""
    print(f"📡 Fetching RSS feed: {rss_url}")
    feed = feedparser.parse(rss_url)

    if not feed.entries:
        print("❌ No episodes found in feed.")
        return None

    latest = feed.entries[0]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENCY_HOURS)

    pub_ts = latest.get("published_parsed")
    if pub_ts:
        pub_dt = datetime.fromtimestamp(calendar.timegm(pub_ts), tz=timezone.utc)
        if pub_dt < cutoff:
            print(f"⏰ Latest episode ({pub_dt.date()}) is older than {RECENCY_HOURS}h. Skipping.")
            return None
    else:
        pub_dt = datetime.now(timezone.utc)

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


def download_audio(url: str, dest_path: str):
    print(f"⬇️  Downloading audio → {dest_path}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                f.write(chunk)
    size_mb = Path(dest_path).stat().st_size / 1024 / 1024
    print(f"   Done ({size_mb:.1f} MB)")


def speed_up_audio(input_path: str) -> str:
    """Return path to a sped-up copy of the audio file using ffmpeg."""
    output_path = input_path.replace(".mp3", "_fast.mp3")
    print(f"⏩ Speeding up audio {AUDIO_SPEED}x with ffmpeg…")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-filter:a", f"atempo={AUDIO_SPEED}",
            "-b:a", "48k",
            "-vn", output_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"   Done ({size_mb:.1f} MB)")
    return output_path


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


def transcribe(audio_path: str) -> tuple[str, float]:
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    print("🎙️  Transcribing with Whisper (this may take a minute)…")
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="zh",
            response_format="text",
        )
    duration_sec = get_audio_duration_seconds(audio_path)
    duration_min = duration_sec / 60
    cost_usd = (duration_sec / 60) * 0.006
    print(f"   Transcript length : {len(result)} chars")
    print(f"   Audio duration    : {duration_min:.1f} min")
    print(f"   Whisper cost      : ${cost_usd:.4f} USD")
    return result, cost_usd
