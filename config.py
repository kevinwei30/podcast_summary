import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

RSS_FEED_URL = "https://feeds.soundcloud.com/users/soundcloud:users:735679489/sounds.rss"
RECENCY_HOURS = 30
AUDIO_SPEED   = 1.25

ANTHROPIC_API_KEY           = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY              = os.getenv("OPENAI_API_KEY")
GMAIL_TO                    = os.getenv("GMAIL_TO")
GMAIL_FROM                  = os.getenv("GMAIL_FROM")
GMAIL_DISPLAY_NAME          = os.getenv("GMAIL_DISPLAY_NAME", "財經皓角摘要")
GMAIL_APP_PASSWORD          = os.getenv("GMAIL_APP_PASSWORD")
SLACK_WEBHOOK_URL           = os.getenv("SLACK_WEBHOOK_URL")
PTT_ID                      = os.getenv("PTT_ID")
PTT_PASSWORD                = os.getenv("PTT_PASSWORD")
PTT_BOARD                   = os.getenv("PTT_BOARD", "Podcast")
IMGBB_API_KEY               = os.getenv("IMGBB_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN   = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
THREADS_ACCESS_TOKEN        = os.getenv("THREADS_ACCESS_TOKEN")
