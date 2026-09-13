import os
import glob
import time
import smtplib
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

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
GEMINI_MODEL = "gemini-2.5-flash"

# India timezone
INDIA_TZ = ZoneInfo("Asia/Kolkata")

# Retry configuration
RETRY_INTERVAL_MINUTES = 5
MAX_RETRIES = 12  # 12 x 5 minutes = approximately 1 hour


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
TO_EMAIL = os.getenv("TO_EMAIL")


# ============================================================
# VALIDATE CONFIGURATION
# ============================================================

def validate_config():
    missing = []

    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")

    if not SMTP_EMAIL:
        missing.append("SMTP_EMAIL")

    if not SMTP_PASSWORD:
        missing.append("SMTP_PASSWORD")

    if not TO_EMAIL:
        missing.append("TO_EMAIL")

    if missing:
        raise Exception(
            "Missing environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(api_key=GEMINI_API_KEY)


# ============================================================
# FILES
# ============================================================

LAST_PROCESSED_FILE = "last_processed.txt"


def get_last_processed_video():
    """
    Return the last YouTube video ID that was processed.
    """

    if not os.path.exists(LAST_PROCESSED_FILE):
        return None

    with open(
        LAST_PROCESSED_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return f.read().strip()


def save_last_processed_video(video_id):
    """
    Save processed YouTube video ID.
    """

    with open(
        LAST_PROCESSED_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(video_id)


# ============================================================
# YOUTUBE RSS
# ============================================================

def get_channel_rss_url():
    return (
        "https://www.youtube.com/feeds/videos.xml"
        f"?channel_id={SONY_SAB_CHANNEL_ID}"
    )


def get_youtube_feed():
    """
    Download Sony SAB's official YouTube RSS feed.
    """

    rss_url = get_channel_rss_url()

    print("\nFetching Sony SAB YouTube feed...")

    request = urllib.request.Request(
        rss_url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        data = response.read()

    return ET.fromstring(data)


# ============================================================
# FIND LATEST TMKOC TEASER
# ============================================================

def find_latest_teaser():
    """
    Find the most recent TMKOC teaser uploaded by Sony SAB.

    Uses the official Sony SAB YouTube RSS feed instead
    of YouTube search results.
    """

    root = get_youtube_feed()

    namespace = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/"
    }

    entries = root.findall(
        "atom:entry",
        namespace
    )

    if not entries:
        print("No videos found in Sony SAB feed.")
        return None

    now = datetime.now(INDIA_TZ)

    candidates = []

    for entry in entries:

        title_element = entry.find(
            "atom:title",
            namespace
        )

        video_id_element = entry.find(
            "yt:videoId",
            namespace
        )

        published_element = entry.find(
            "atom:published",
            namespace
        )

        if (
            title_element is None
            or video_id_element is None
            or published_element is None
        ):
            continue

        title = title_element.text or ""
        video_id = video_id_element.text or ""
        published_string = published_element.text or ""

        # ----------------------------------------------------
        # Check whether this is a TMKOC teaser
        # ----------------------------------------------------

        title_lower = title.lower()

        is_tmkoc = (
            "taarak mehta" in title_lower
            or "tmkoc" in title_lower
        )

        is_teaser = (
            "teaser" in title_lower
            or "promo" in title_lower
        )

        if not (is_tmkoc and is_teaser):
            continue

        # ----------------------------------------------------
        # Parse publication date
        # ----------------------------------------------------

        try:
            published_dt = datetime.fromisoformat(
                published_string.replace(
                    "Z",
                    "+00:00"
                )
            )

            published_dt = published_dt.astimezone(
                INDIA_TZ
            )

        except Exception:
            continue

        # ----------------------------------------------------
        # Ignore videos older than 2 days
        #
        # This prevents the bot from accidentally summarizing
        # an old teaser if today's teaser hasn't appeared yet.
        # ----------------------------------------------------

        age = now - published_dt

        if age > timedelta(days=2):
            continue

        if published_dt > now:
            continue

        video_url = (
            f"https://www.youtube.com/watch?v={video_id}"
        )

        candidates.append({
            "title": title,
            "video_id": video_id,
            "url": video_url,
            "published": published_dt
        })

    if not candidates:
        print("No recent TMKOC teaser found.")
        return None

    # Newest first
    candidates.sort(
        key=lambda x: x["published"],
        reverse=True
    )

    latest = candidates[0]

    print("\nFound:")
    print(latest["title"])
    print(latest["url"])
    print(
        "Published:",
        latest["published"].strftime(
            "%d %B %Y %I:%M %p"
        )
    )

    return latest


# ============================================================
# WAIT FOR TODAY'S TEASER
# ============================================================

def find_teaser_with_retries():
    """
    Check repeatedly for a recent teaser.

    This is useful because the script may run at 9:15 PM
    while Sony SAB uploads the teaser a few minutes later.
    """

    for attempt in range(1, MAX_RETRIES + 1):

        print(
            f"\nChecking for teaser "
            f"(attempt {attempt}/{MAX_RETRIES})..."
        )

        teaser = find_latest_teaser()

        if teaser is not None:

            last_processed = (
                get_last_processed_video()
            )

            if (
                teaser["video_id"]
                == last_processed
            ):
                print(
                    "\nThis teaser was already processed."
                )
                return None

            return teaser

        if attempt < MAX_RETRIES:

            print(
                f"No new teaser yet. "
                f"Waiting {RETRY_INTERVAL_MINUTES} minutes..."
            )

            time.sleep(
                RETRY_INTERVAL_MINUTES * 60
            )

    print(
        "\nNo recent TMKOC teaser appeared "
        "during the retry window."
    )

    return None


# ============================================================
# DOWNLOAD VIDEO
# ============================================================

def download_video(video_url):
    """
    Download the teaser using yt-dlp.

    Node.js is explicitly enabled because newer YouTube
    extraction requires a JavaScript runtime.
    """

    print("\nDownloading teaser video...")

    os.makedirs(
        DOWNLOAD_DIR,
        exist_ok=True
    )

    # Remove previous downloads
    for old_file in glob.glob(
        os.path.join(
            DOWNLOAD_DIR,
            "tmkoc_teaser.*"
        )
    ):
        try:
            os.remove(old_file)
        except Exception:
            pass

    output_template = os.path.join(
        DOWNLOAD_DIR,
        "tmkoc_teaser.%(ext)s"
    )

    options = {
        # Best video + best audio, falling back to
        # the best single file available.
        "format": "bv*+ba/b",

        "outtmpl": output_template,

        "merge_output_format": "mp4",

        "noplaylist": True,

        "quiet": False,

        # Use Node.js for YouTube's JS challenges.
        "js_runtimes": {
            "node": {}
        },
    }

    try:

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([video_url])

    except Exception as e:

        print("\nDownload failed:")
        print(str(e))

        raise

    # Find downloaded video
    files = glob.glob(
        os.path.join(
            DOWNLOAD_DIR,
            "tmkoc_teaser.*"
        )
    )

    video_files = [
        f for f in files
        if f.lower().endswith(
            (
                ".mp4",
                ".mkv",
                ".webm",
                ".mov",
                ".m4v"
            )
        )
    ]

    if not video_files:
        raise Exception(
            "Video download failed: "
            "no video file found."
        )

    video_file = video_files[0]

    print(
        f"\nDownloaded successfully:\n"
        f"{video_file}"
    )

    return video_file


# ============================================================
# UPLOAD VIDEO TO GEMINI
# ============================================================

def upload_video(video_file):
    """
    Upload downloaded teaser to Gemini Files API.
    """

    print("\nUploading teaser to Gemini...")

    uploaded_file = client.files.upload(
        file=video_file
    )

    print(
        "Gemini file uploaded:",
        uploaded_file.name
    )

    # Wait until Gemini finishes processing
    print("Waiting for Gemini to process video...")

    while True:

        uploaded_file = client.files.get(
            name=uploaded_file.name
        )

        state = uploaded_file.state.name

        print(
            "Gemini file state:",
            state
        )

        if state == "ACTIVE":
            break

        if state == "FAILED":
            raise Exception(
                "Gemini failed to process "
                "the uploaded video."
            )

        time.sleep(3)

    print("Video is ready for analysis.")

    return uploaded_file


# ============================================================
# SUMMARIZE VIDEO
# ============================================================

def summarize_video(uploaded_file, teaser_title):
    """
    Ask Gemini to watch and summarize the teaser.
    """

    print("\nAnalyzing teaser with Gemini...")

    prompt = f"""
You are analyzing an official Taarak Mehta Ka Ooltah Chashmah
(TMKOC) episode teaser from Sony SAB.

Video title:
{teaser_title}

Watch the ENTIRE video carefully.

Analyze both:
1. Spoken dialogue
2. Visual actions and events

Do not rely only on the title.

Create a concise but useful summary in English.

Include:

1. Episode number, if visible or inferable from the title
2. Main characters appearing in the teaser
3. What happens in the teaser
4. The main problem/conflict
5. Important dialogue or revelation, paraphrased
6. What appears likely to happen in the upcoming episode

Important rules:

- Do NOT invent events.
- Do NOT assume things that are not shown or reasonably supported.
- Clearly distinguish what is shown from what is only suggested.
- Focus on the actual events of this teaser.
- Avoid generic descriptions of TMKOC.
- Keep the final response around 150-250 words.
- Make it easy to read.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            uploaded_file,
            prompt
        ]
    )

    summary = response.text

    if not summary:
        raise Exception(
            "Gemini returned an empty summary."
        )

    print("\nGemini summary generated.")

    return summary.strip()


# ============================================================
# DELETE GEMINI FILE
# ============================================================

def delete_gemini_file(uploaded_file):
    """
    Delete uploaded video from Gemini after processing.
    """

    try:

        client.files.delete(
            name=uploaded_file.name
        )

        print(
            "Deleted temporary Gemini file."
        )

    except Exception as e:

        print(
            "Could not delete Gemini file:",
            e
        )


# ============================================================
# SEND EMAIL
# ============================================================

def send_email(teaser, summary):
    """
    Send summary through Gmail SMTP.
    """

    print("\nSending email...")

    subject = (
        f"TMKOC Teaser Summary - "
        f"{teaser['title']}"
    )

    body = f"""
TMKOC TEASER SUMMARY
====================

{teaser['title']}

Published:
{teaser['published'].strftime('%d %B %Y, %I:%M %p')}

YouTube:
{teaser['url']}


SUMMARY
-------

{summary}


Generated automatically by your TMKOC Teaser Bot.
"""

    message = MIMEMultipart()

    message["From"] = SMTP_EMAIL
    message["To"] = TO_EMAIL
    message["Subject"] = subject

    message.attach(
        MIMEText(
            body,
            "plain",
            "utf-8"
        )
    )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465
    ) as server:

        server.login(
            SMTP_EMAIL,
            SMTP_PASSWORD
        )

        server.sendmail(
            SMTP_EMAIL,
            TO_EMAIL,
            message.as_string()
        )

    print("Email sent successfully.")


# ============================================================
# CLEANUP LOCAL VIDEO
# ============================================================

def cleanup():
    """
    Delete downloaded teaser files.
    """

    print("\nCleaning up...")

    for file in glob.glob(
        os.path.join(
            DOWNLOAD_DIR,
            "tmkoc_teaser.*"
        )
    ):
        try:
            os.remove(file)
            print(
                "Deleted:",
                file
            )
        except Exception as e:
            print(
                "Could not delete:",
                file,
                e
            )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("TMKOC GEMINI TEASER BOT - TEST MODE")
    print("=" * 60)

    validate_config()

    # Put the 16-hour-old teaser URL here
    test_url = "https://www.youtube.com/watch?v=cLj_hOOZeeg"

    teaser = {
        "title": "TMKOC Test Teaser",
        "video_id": test_url.split("v=")[-1],
        "url": test_url,
        "published": datetime.now(INDIA_TZ)
    }

    try:
        # 1. Download
        video_file = download_video(test_url)

        uploaded_file = None

        try:
            # 2. Upload to Gemini
            uploaded_file = upload_video(video_file)

            # 3. Ask Gemini to analyze it
            summary = summarize_video(
                uploaded_file,
                teaser["title"]
            )

            print("\n" + "=" * 60)
            print("GEMINI SUMMARY")
            print("=" * 60)
            print(summary)

            # 4. Send email
            send_email(teaser, summary)

            print("\nTest completed successfully!")

        finally:
            if uploaded_file:
                delete_gemini_file(uploaded_file)

            cleanup()

    except Exception as e:
        print("\nTEST FAILED:")
        print(e)
        cleanup()

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()