import base64
import smtplib
import requests
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from config import (
    GMAIL_FROM, GMAIL_TO, GMAIL_APP_PASSWORD, GMAIL_DISPLAY_NAME,
    SLACK_WEBHOOK_URL,
    PTT_ID, PTT_PASSWORD, PTT_BOARD,
    IMGBB_API_KEY,
    LINE_CHANNEL_ACCESS_TOKEN,
    THREADS_ACCESS_TOKEN,
)


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


def upload_to_imgbb(image_path: Path) -> str | None:
    """Upload image to imgbb and return the public URL, or None on failure."""
    if not IMGBB_API_KEY:
        print("🖼️  imgbb skipped (IMGBB_API_KEY not set)")
        return None
    print("🖼️  Uploading infographic to imgbb…")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": IMGBB_API_KEY, "image": b64},
        timeout=30,
    )
    if resp.status_code == 200 and resp.json().get("success"):
        url = resp.json()["data"]["url"]
        print(f"   Uploaded → {url}")
        return url
    print(f"   imgbb upload failed (HTTP {resp.status_code}: {resp.text})")
    return None


def send_line(image_url: str | None, text: str):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("💚 LINE skipped (LINE_CHANNEL_ACCESS_TOKEN not set)")
        return
    print("💚 Broadcasting to LINE…")
    messages = []
    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url,
        })
    messages.append({"type": "text", "text": text[:5000]})
    resp = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
        json={"messages": messages},
        timeout=15,
    )
    if resp.status_code == 200:
        print("   LINE sent ✅")
    else:
        print(f"   LINE delivery failed (HTTP {resp.status_code}: {resp.text})")


def send_threads(image_url: str | None, caption: str):
    if not THREADS_ACCESS_TOKEN:
        print("🧵 Threads skipped (THREADS_ACCESS_TOKEN not set)")
        return
    print("🧵 Posting to Threads…")
    truncated = caption[:497] + "…" if len(caption) > 500 else caption
    try:
        params = {"text": truncated, "access_token": THREADS_ACCESS_TOKEN}
        if image_url:
            params["media_type"] = "IMAGE"
            params["image_url"] = image_url
        else:
            params["media_type"] = "TEXT"
        r1 = requests.post(
            "https://graph.threads.net/v1.0/me/threads",
            params=params,
            timeout=15,
        )
        r1.raise_for_status()
        creation_id = r1.json()["id"]
        r2 = requests.post(
            "https://graph.threads.net/v1.0/me/threads_publish",
            params={"creation_id": creation_id, "access_token": THREADS_ACCESS_TOKEN},
            timeout=15,
        )
        r2.raise_for_status()
        print("   Threads post sent ✅")
    except Exception as e:
        print(f"   Threads post failed: {e}")


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
