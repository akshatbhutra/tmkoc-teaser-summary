import os
import glob
import time
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

# Sony SAB official YouTube channel ID
SONY_SAB_CHANNEL_ID = "UC6-F5tO8uklgE9Zy8IvbdFw"

# Folder for downloaded teaser audio
DOWNLOAD_DIR = "downloads"

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
# FIND LATEST TMKOC TEASER VIA YT-DLP PLAYLIST
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
        "proxy": os.getenv("INDIAN_PROXY_URL"),
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
# DOWNLOAD AUDIO ONLY (BYPASSES CLOUD GEO-BLOCKING)
# ============================================================

def download_audio(video_url):
    print("\nDownloading teaser audio stream (cloud-optimized)...")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    for old_file in glob.glob(os.path.join(DOWNLOAD_DIR, "tmkoc_teaser.*")):
        try:
            os.remove(old_file)
        except Exception:
            pass

    output_template = os.path.join(DOWNLOAD_DIR, "tmkoc_teaser.%(ext)s")

    options = {
        "format": "m4a/bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "geo_bypass": True,
        "geo_bypass_country": "IN",
        "proxy": os.getenv("INDIAN_PROXY_URL"),  # Added proxy support
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "js_runtimes": {
            "node": {}
        },
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([video_url])
    except Exception as e:
        print("\nAudio download failed:", str(e))
        raise

    files = glob.glob(os.path.join(DOWNLOAD_DIR, "tmkoc_teaser.*"))
    audio_files = [
        f for f in files
        if f.lower().endswith((".m4a", ".mp3", ".aac", ".wav", ".opus"))
    ]

    if not audio_files:
        raise Exception("Audio download failed: no audio file found.")

    audio_file = audio_files[0]
    print(f"Audio downloaded successfully: {audio_file}")
    return audio_file


# ============================================================
# UPLOAD AUDIO TO GEMINI
# ============================================================

def upload_audio(audio_file):
    print("\nUploading teaser audio to Gemini...")
    uploaded_file = client.files.upload(file=audio_file)
    print("Gemini file uploaded:", uploaded_file.name)

    print("Waiting for Gemini to process audio...")
    while True:
        uploaded_file = client.files.get(name=uploaded_file.name)
        state = uploaded_file.state.name
        print("Gemini file state:", state)

        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise Exception("Gemini failed to process the uploaded audio.")

        time.sleep(3)

    print("Audio is ready for analysis.")
    return uploaded_file


# ============================================================
# SUMMARIZE AUDIO
# ============================================================

def summarize_audio(uploaded_file, teaser_title):
    print("\nAnalyzing teaser audio with Gemini...")

    prompt = f"""
You are analyzing the official audio teaser from Taarak Mehta Ka Ooltah Chashmah (TMKOC) episode by Sony SAB.

Video title:
{teaser_title}

Listen carefully to the audio dialogue, character voices, and sound effects.

Create a concise, engaging summary in English (150-250 words) covering:
1. Episode number, if visible or inferable from the title
2. Main characters speaking or involved in the dialogue
3. What happens in the upcoming episode based on the audio details
4. The main problem or conflict highlighted
5. Important dialogue exchanges or revelations, paraphrased
6. What viewers can expect

Important rules:
- Do NOT invent events or assume things not mentioned.
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

    # 1. Automatically find latest teaser from Sony SAB channel
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
        # 2. Download audio stream only (bypasses region block on GitHub Actions)
        audio_file = download_audio(teaser["url"])

        # 3. Upload audio to Gemini Files API
        uploaded_file = upload_audio(audio_file)

        # 4. Generate summary from audio content
        summary = summarize_audio(uploaded_file, teaser["title"])

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