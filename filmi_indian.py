# filmi_indian.py
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import sys

def main():
    # The unique YouTube Channel ID for @FilmiIndian
    channel_id = "UCeiAKuJGZrIjYvaq0nMwbJg"
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    # Ask the user for the timeframe in hours
    try:
        hours_input = input("Enter timeframe in hours (e.g., 24 for the last 24 hours): ")
        hours = float(hours_input)
    except ValueError:
        print("Invalid input. Please enter a valid number of hours.")
        sys.exit(1)

    print(f"\nScanning recent uploads from @FilmiIndian for the last {hours} hours...")
    
    # Fetch the YouTube RSS feed
    try:
        req = urllib.request.Request(feed_url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        xml_data = response.read()
    except Exception as e:
        print(f"Error connecting to YouTube: {e}")
        sys.exit(1)

    # Parse XML data
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        print("Error parsing data from YouTube.")
        sys.exit(1)
        
    # YouTube uses Atom XML namespaces
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'yt': 'http://www.youtube.com/xml/schemas/2015'
    }
    
    # Calculate the time cutoff
    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=hours)
    
    found_reviews = []
    
    # Iterate over all videos in the channel's feed
    for entry in root.findall('atom:entry', ns):
        title = entry.find('atom:title', ns).text
        link = entry.find('atom:link', ns).attrib['href']
        published_str = entry.find('atom:published', ns).text
        
        # YouTube returns time in ISO 8601 (e.g., 2026-09-17T12:30:00+00:00)
        published_str = published_str.replace('Z', '+00:00')
        published_time = datetime.fromisoformat(published_str)
        
        # Check if the video was published within the requested timeframe
        if published_time >= time_threshold:
            # Check for "Movie Review" as a substring (case-insensitive)
            if "movie review" in title.lower():
                found_reviews.append({
                    'title': title,
                    'link': link,
                    'published': published_time
                })

    # Display the results
    print("\n" + "="*70)
    if not found_reviews:
        print(f"No videos with 'Movie Review' found in the last {hours} hours.")
    else:
        print(f"Found {len(found_reviews)} movie review(s) in the last {hours} hours:")
        print("="*70)
        for idx, review in enumerate(found_reviews, 1):
            # Convert UTC time to your computer's local time zone for readability
            local_time = review['published'].astimezone().strftime('%b %d, %Y - %I:%M %p')
            print(f"{idx}. {review['title']}")
            print(f"   Published: {local_time}")
            print(f"   Watch here: {review['link']}")
            print("-" * 70)

if __name__ == "__main__":
    main()