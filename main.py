import os
import glob
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import yt_dlp
from dotenv import load_dotenv
from google import genai


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

# Sony SAB official YouTube channel
SONY_SAB_CHANNEL_ID = "UC6-F5tO8uklgE9Zy8IvbdFw"

# Folder for downloaded teaser
DOWNLOAD_DIR = "downloads"

# Gemini model
GEMINI_MODEL = "gemini-3.6-flash"

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
# YOUTUBE RSS & TEASER DISCOVERY
# ============================================================

def get_channel_rss_url():
    return (
        "https://www.youtube.com/feeds/videos.xml"
        f"?channel_id={SONY_SAB_CHANNEL_ID}"
    )


import requests

def get_youtube_feed():
    """
    Download Sony SAB's official YouTube RSS feed using requests.
    """
    print("\nFetching Sony SAB YouTube RSS feed...")
    rss_url = get_channel_rss_url()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    response = requests.get(rss_url, headers=headers, timeout=30)
    response.raise_for_status()

    return ET.fromstring(response.content)


# ============================================================
# FIND LATEST TMKOC TEASER VIA YT-DLP
# ============================================================

def find_latest_teaser():
    """
    Find the most recent TMKOC teaser uploaded by Sony SAB 
    using the reliable YouTube uploads playlist URL.
    """
    print("\nFetching latest videos from Sony SAB playlist...")
    # Convert channel ID (UC...) to uploads playlist ID (UU...)
    playlist_id = "UU" + SONY_SAB_CHANNEL_ID[2:]
    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

    ydl_opts = {
        "extract_flat": True,
        "playlistend": 25,
        "quiet": True,
        "geo_bypass": True,
        "geo_bypass_country": "IN",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "js_runtimes": {
            "node": {}
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(playlist_url, download=False)

        if not result or "entries" not in result:
            print("No videos found in playlist response.")
            return None

        entries = result["entries"]
    except Exception as e:
        print(f"Failed to fetch playlist entries: {e}")
        return None

    now = datetime.now(INDIA_TZ)
    candidates = []

    for entry in entries:
        title = entry.get("title", "")
        video_id = entry.get("id", "")

        if not title or not video_id:
            continue

        title_lower = title.lower()

        # Matches pattern: "Taarak Mehta..." or "TMKOC" + "Teaser" or "Promo"
        is_tmkoc = "taarak mehta" in title_lower or "tmkoc" in title_lower
        is_teaser = "teaser" in title_lower or "promo" in title_lower

        if not (is_tmkoc and is_teaser):
            continue

        upload_date_str = entry.get("upload_date")  # Format: YYYYMMDD
        if upload_date_str:
            try:
                published_dt = datetime.strptime(upload_date_str, "%Y%m%d").replace(tzinfo=INDIA_TZ)
            except Exception:
                published_dt = now
        else:
            published_dt = now

        # Ignore videos older than 5 days
        if (now - published_dt) > timedelta(days=5) or published_dt > now:
            continue

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        candidates.append({
            "title": title,
            "video_id": video_id,
            "url": video_url,
            "published": published_dt
        })

    if not candidates:
        print("No recent TMKOC teaser found.")
        return None

    # Sort newest first
    candidates.sort(key=lambda x: x["published"], reverse=True)
    latest = candidates[0]

    print("\nFound Latest Teaser:")
    print(latest["title"])
    print(latest["url"])
    print("Published:", latest["published"].strftime("%d %B %Y"))

    return latest

# ============================================================
# DOWNLOAD VIDEO (OPTIMIZED FOR SPEED)
# ============================================================

def download_video(video_url):
    print("\nDownloading teaser video (optimized)...")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    for old_file in glob.glob(os.path.join(DOWNLOAD_DIR, "tmkoc_teaser.*")):
        try:
            os.remove(old_file)
        except Exception:
            pass

    output_template = os.path.join(DOWNLOAD_DIR, "tmkoc_teaser.%(ext)s")

    options = {
        "format": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "js_runtimes": {
            "node": {}
        },
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([video_url])
    except Exception as e:
        print("\nDownload failed:", str(e))
        raise

    files = glob.glob(os.path.join(DOWNLOAD_DIR, "tmkoc_teaser.*"))
    video_files = [
        f for f in files
        if f.lower().endswith((".mp4", ".mkv", ".webm", ".mov", ".m4v"))
    ]

    if not video_files:
        raise Exception("Video download failed: no video file found.")

    video_file = video_files[0]
    print(f"Downloaded successfully: {video_file}")
    return video_file


# ============================================================
# UPLOAD VIDEO TO GEMINI
# ============================================================

def upload_video(video_file):
    print("\nUploading teaser to Gemini...")
    uploaded_file = client.files.upload(file=video_file)
    print("Gemini file uploaded:", uploaded_file.name)

    print("Waiting for Gemini to process video...")
    while True:
        uploaded_file = client.files.get(name=uploaded_file.name)
        state = uploaded_file.state.name
        print("Gemini file state:", state)

        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise Exception("Gemini failed to process the uploaded video.")

        time.sleep(3)

    print("Video is ready for analysis.")
    return uploaded_file


# ============================================================
# SUMMARIZE VIDEO
# ============================================================

def summarize_video(uploaded_file, teaser_title):
    print("\nAnalyzing teaser with Gemini...")

    prompt = f"""
You are analyzing an official Taarak Mehta Ka Ooltah Chashmah (TMKOC) episode teaser from Sony SAB.

Video title:
{teaser_title}

Watch the ENTIRE video carefully. Analyze both spoken dialogue and visual actions/events.

Create a concise, engaging summary in English (150-250 words) covering:
1. Episode number, if visible or inferable from the title
2. Main characters appearing in the teaser
3. What happens in the teaser
4. The main problem/conflict
5. Important dialogue or revelation, paraphrased
6. What appears likely to happen in the upcoming episode

Important rules:
- Do NOT invent events or assume things not shown.
- Clearly distinguish what is shown from what is suggested.
- Keep it easy to read with bullet points or structured sections.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[uploaded_file, prompt]
    )

    summary = response.text
    if not summary:
        raise Exception("Gemini returned an empty summary.")

    print("\nGemini summary generated.")
    return summary.strip()


# ============================================================
# DELETE GEMINI FILE & LOCAL CLEANUP
# ============================================================

def delete_gemini_file(uploaded_file):
    try:
        client.files.delete(name=uploaded_file.name)
        print("Deleted temporary Gemini file.")
    except Exception as e:
        print("Could not delete Gemini file:", e)


def cleanup():
    print("\nCleaning up local downloads...")
    for file in glob.glob(os.path.join(DOWNLOAD_DIR, "tmkoc_teaser.*")):
        try:
            os.remove(file)
            print("Deleted:", file)
        except Exception as e:
            print("Could not delete:", file, e)


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

    # 1. Automatically find latest teaser from Sony SAB RSS feed
    teaser = find_latest_teaser()
    if not teaser:
        print("No eligible teaser found at this moment.")
        return

    # Check if this video was already processed
    last_processed = get_last_processed_video()
    if teaser["video_id"] == last_processed:
        print("\nThis teaser has already been processed and sent. Exiting.")
        return

    uploaded_file = None

    try:
        # 2. Download optimized video
        video_file = download_video(teaser["url"])

        # 3. Upload to Gemini Files API
        uploaded_file = upload_video(video_file)

        # 4. Generate summary
        summary = summarize_video(uploaded_file, teaser["title"])

        print("\n" + "=" * 60)
        print("GEMINI SUMMARY OUTPUT")
        print("=" * 60)
        print(summary)
        print("=" * 60)

        # 5. Send to WhatsApp
        send_whatsapp(teaser, summary)

        # 6. Save video ID so it doesn't process again
        save_last_processed_video(teaser["video_id"])
        print("\nProcess completed successfully!")

    except Exception as e:
        print("\nAUTOMATION FAILED:")
        print(e)

    finally:
        if uploaded_file:
            delete_gemini_file(uploaded_file)
        cleanup()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()