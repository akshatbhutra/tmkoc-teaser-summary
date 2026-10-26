import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from google import genai

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

# Sony SAB official YouTube channel ID
SONY_SAB_CHANNEL_ID = "UC6-F5tO8uklgE9Zy8IvbdFw"

# Gemini model
GEMINI_MODEL = "gemini-3.5-flash"

# India timezone
INDIA_TZ = ZoneInfo("Asia/Kolkata")

# File to track already processed video IDs to prevent duplicate sends
LAST_PROCESSED_FILE = "last_processed.txt"


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER")


# ============================================================
# VALIDATE CONFIGURATION
# ============================================================

def validate_config():
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not EVOLUTION_API_URL:
        missing.append("EVOLUTION_API_URL")
    if not EVOLUTION_API_KEY:
        missing.append("EVOLUTION_API_KEY")
    if not WHATSAPP_NUMBER:
        missing.append("WHATSAPP_NUMBER")

    if missing:
        raise Exception(
            "Missing environment variables in .env: " + ", ".join(missing)
        )


# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(api_key=GEMINI_API_KEY)


# ============================================================
# TRACKING PROCESSED VIDEOS
# ============================================================

def get_last_processed_video():
    if not os.path.exists(LAST_PROCESSED_FILE):
        return None
    with open(LAST_PROCESSED_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def save_last_processed_video(video_id):
    with open(LAST_PROCESSED_FILE, "w", encoding="utf-8") as f:
        f.write(video_id)


# ============================================================
# FIND LATEST TMKOC TEASER VIA RSS XML FEED
# ============================================================

# ============================================================
# FIND LATEST TMKOC TEASER (CHECKING LAST 25 VIDEOS VIA YT-DLP)
# ============================================================

def find_latest_teaser():
    """
    Find the most recent TMKOC teaser uploaded by Sony SAB 
    by checking the last 25 uploads using yt-dlp flat extraction.
    """
    print("\nFetching latest videos from Sony SAB channel (checking last 25)...")
    channel_url = f"https://www.youtube.com/channel/{SONY_SAB_CHANNEL_ID}/videos"

    ydl_opts = {
        "extract_flat": True,       # Extract metadata without downloading video binaries
        "playlistend": 25,          # Check the last 25 uploads
        "quiet": True,
        "geo_bypass": True,
        "geo_bypass_country": "IN",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "js_runtimes": {
            "node": {}
        },
    }

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(channel_url, download=False)
            
        if not result or "entries" not in result:
            print("No videos found in channel response.")
            return None

        entries = result["entries"]
    except Exception as e:
        print(f"Failed to fetch channel entries: {e}")
        return None

    now = datetime.now(INDIA_TZ)
    candidates = []

    for entry in entries:
        title = entry.get("title", "")
        video_id = entry.get("id", "")
        description = entry.get("description", "")

        if not title or not video_id:
            continue

        title_lower = title.lower()

        # Matches pattern: "Taarak Mehta..." or "TMKOC" + "Teaser" or "Promo"
        is_tmkoc = "taarak mehta" in title_lower or "tmkoc" in title_lower
        is_teaser = "teaser" in title_lower or "promo" in title_lower

        if not (is_tmkoc and is_teaser):
            continue

        upload_date_str = entry.get("upload_date") # Format: YYYYMMDD
        if upload_date_str:
            try:
                published_dt = datetime.strptime(upload_date_str, "%Y%m%d").replace(tzinfo=INDIA_TZ)
            except Exception:
                published_dt = now
        else:
            published_dt = now

        # Ignore videos older than 5 days (as configured in your timedelta check)
        if (now - published_dt) > timedelta(days=5) or published_dt > now:
            continue

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        candidates.append({
            "title": title,
            "video_id": video_id,
            "url": video_url,
            "description": description,
            "published": published_dt
        })

    if not candidates:
        print("No recent TMKOC teaser found.")
        return None

    candidates.sort(key=lambda x: x["published"], reverse=True)
    latest = candidates[0]

    print("\nFound Latest Teaser:")
    print(latest["title"])
    print(latest["url"])
    print("Published:", latest["published"].strftime("%d %B %Y %H:%M"))

    return latest
# ============================================================
# SUMMARIZE VIDEO METADATA WITH GEMINI
# ============================================================

def summarize_teaser(teaser_title, teaser_description):
    print("\nGenerating summary with Gemini...")

    prompt = f"""
You are analyzing an official Taarak Mehta Ka Ooltah Chashmah (TMKOC) episode teaser from Sony SAB based on its official metadata.

Video Title:
{teaser_title}

Video Description:
{teaser_description}

Create a concise, engaging summary in English (150-250 words) covering:
1. Episode number, if visible or inferable from the title/description
2. Main characters involved or mentioned
3. What happens in the upcoming episode based on the official teaser details
4. The main conflict or storyline highlighted
5. What viewers can expect

Important rules:
- Do NOT invent events or assume things not mentioned.
- Keep it easy to read with bullet points or structured sections.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    summary = response.text
    if not summary:
        raise Exception("Gemini returned an empty summary.")

    print("\nGemini summary generated.")
    return summary.strip()


# ============================================================
# SEND WHATSAPP MESSAGE
# ============================================================

def send_whatsapp(teaser, summary):
    print("\nSending summary to WhatsApp...")
    url = f"{EVOLUTION_API_URL}/message/sendText/n8n_whatsapp"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

    message = (
        f"📺 *TMKOC Teaser Summary*\n"
        f"*{teaser['title']}*\n\n"
        f"{summary}\n\n"
        f"🔗 Watch: {teaser['url']}"
    )

    payload = {
        "number": WHATSAPP_NUMBER,
        "text": message
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code in (200, 201):
        print("WhatsApp message sent successfully!")
    else:
        print(f"Failed to send WhatsApp message. Status: {response.status_code}, Response: {response.text}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("TMKOC GEMINI TEASER AUTOMATION BOT")
    print("=" * 60)

    validate_config()

    teaser = find_latest_teaser()
    if not teaser:
        print("No eligible teaser found at this moment.")
        return

    last_processed = get_last_processed_video()
    if teaser["video_id"] == last_processed:
        print("\nThis teaser has already been processed and sent. Exiting.")
        return

    try:
        summary = summarize_teaser(teaser["title"], teaser["description"])

        print("\n" + "=" * 60)
        print("GEMINI SUMMARY OUTPUT")
        print("=" * 60)
        print(summary)
        print("=" * 60)

        send_whatsapp(teaser, summary)

        save_last_processed_video(teaser["video_id"])
        print("\nProcess completed successfully!")

    except Exception as e:
        print("\nAUTOMATION FAILED:")
        print(e)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()