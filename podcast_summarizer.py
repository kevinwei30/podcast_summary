#!/usr/bin/env python3
"""
podcast_summarizer.py
─────────────────────
Daily automated summarizer for 游庭皓的財經皓角.

Flow:
  1. Parse RSS feed → find today's (or latest) episode
  2. Download and transcribe the audio (Whisper)
  3. Summarize with Claude
  4. Generate an infographic (Claude + Playwright)
  5. Deliver via Email / Slack / LINE / Threads / PTT

Modules:
  config.py   – environment variables and constants
  audio.py    – RSS, download, speed-up, transcription
  ai.py       – summarization and infographic generation
  deliver.py  – all delivery channels
"""

import sys
import argparse
import tempfile
from datetime import datetime
from pathlib import Path

from config import RSS_FEED_URL
from audio import get_latest_episode, download_audio, speed_up_audio, transcribe
from ai import summarize, generate_infographic
from deliver import upload_to_imgbb, send_email, send_slack, send_line, send_threads, send_ptt


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", help="Path to existing transcript.txt to skip download/transcription")
    parser.add_argument("--summary", help="Path to existing summary.txt to skip everything and just deliver")
    parser.add_argument("--verbose", action="store_true", help="Print full summary to console (useful for CI logs)")
    args = parser.parse_args()

    Path("output").mkdir(exist_ok=True)
    run_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    tee = Tee(Path(f"output/run_{run_ts}.log"))

    print("=" * 60)
    print("  財經皓角 Daily Summarizer")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    cost_transcribe  = 0.0
    cost_summarize   = 0.0
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
        summary = None

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
        summary = None

    # ── Stage 2: summarize ───────────────────────────────────────────────────
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
    image_url = upload_to_imgbb(out_dir / "infographic.png")
    send_email(subject, summary, image_path=out_dir / "infographic.png")
    send_slack(full_output)
    send_line(image_url, full_output)
    send_threads(image_url, summary)
    ptt_title = f"[心得] 財經皓角每日摘要 — {episode_title}"
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
