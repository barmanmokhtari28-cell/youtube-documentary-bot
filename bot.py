import os
import re
import sys
import html
import time
import requests
import feedparser
import yt_dlp
from datetime import datetime
from deep_translator import GoogleTranslator

# ==========================================
# CONFIGURATION SETTINGS
# ==========================================
SENT_VIDEOS_FILE = "sent_videos.txt"

# Your exact Telegram channel handle
CHANNEL_USERNAME = "@secretollah" 

# Target YouTube Channel IDs to monitor
YOUTUBE_CHANNELS = {
    "Vox": "UC3tLa_ia6MU9869u8K7p_3g",
    "Johnny Harris": "UCmGSJVG3mCRrOPgPh8777HQ",
    "Kurzgesagt – In a Nutshell": "UCsXVk37bltUxLHfbjXE-F8g",
    "Veritasium": "UCHnyfMqiRRG1u-2MsSQLbXA",
    "TED-Ed": "UCsooa4yRKGN_zEE8iknghZA"
}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# ==========================================

def get_sent_videos():
    if not os.path.exists(SENT_POSTS_FILE := SENT_VIDEOS_FILE):
        return set()
    with open(SENT_POSTS_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_video(video_id):
    with open(SENT_VIDEOS_FILE, "a") as f:
        f.write(f"{video_id}\n")

def translate_to_persian(text):
    if not text.strip():
        return ""
    try:
        translated = GoogleTranslator(source='en', target='fa').translate(text)
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return ""

def download_youtube_video(video_url, video_id):
    output_filename = f"video_{video_id}.mp4"
    print(f"Downloading and compressing video to: {output_filename}")
    
    ydl_opts = {
        # Limit format to 360p or lower to keep file sizes very small
        'format': 'bestvideo[height<=360]+bestaudio/best[height<=360]/worst',
        'outtmpl': f'video_{video_id}.%(ext)s',
        'recode_video': 'mp4',  # Auto-transcode to MP4 natively via yt-dlp
        'quiet': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # If the file exists directly as .mp4, return it
        if os.path.exists(output_filename):
            return output_filename
            
        # In case the file downloaded as .webm/.mkv, transcode it manually with ffmpeg
        for file in os.listdir('.'):
            if file.startswith(f"video_{video_id}"):
                if not file.endswith('.mp4'):
                    import subprocess
                    print(f"Manually transcoding {file} to MP4 using ffmpeg...")
                    try:
                        subprocess.run([
                            'ffmpeg', '-y', '-i', file,
                            '-vcodec', 'libx264', '-acodec', 'aac',
                            '-crf', '28', '-preset', 'veryfast',
                            output_filename
                        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        os.remove(file)  # Clean up the original webm/mkv file
                        return output_filename
                    except Exception as trans_err:
                        print(f"Manual transcode failed: {trans_err}")
                else:
                    return file
    except Exception as e:
        print(f"yt-dlp download error: {e}")
        
    return None

def download_thumbnail(video_id):
    urls_to_try = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    ]
    local_filename = f"thumb_{video_id}.jpg"
    for url in urls_to_try:
        try:
            r = requests.get(url, stream=True, timeout=15)
            if r.status_code == 200:
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                return local_filename
        except Exception as e:
            print(f"Failed to fetch thumbnail from {url}: {e}")
    return None

def send_telegram_video(video_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    with open(video_path, "rb") as video:
        files = {"video": video}
        data = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "caption": caption,
            "parse_mode": "HTML"
        }
        res = requests.post(url, files=files, data=data)
        if res.status_code != 200:
            print(f"Failed to send video: {res.text}")
            return False
        return True

def send_telegram_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        files = {"photo": photo}
        data = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "caption": caption,
            "parse_mode": "HTML"
        }
        res = requests.post(url, files=files, data=data)
        if res.status_code != 200:
            print(f"Failed to send photo: {res.text}")
            return False
        return True

def clean_html_text(raw_html):
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text().strip()

def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Secrets missing in environment configuration.")
        sys.exit(1)

    sent_videos = get_sent_videos()
    all_new_videos = []

    for channel_name, channel_id in YOUTUBE_CHANNELS.items():
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        print(f"Checking updates for {channel_name}...")
        feed = feedparser.parse(feed_url)
        
        # Pull up to 4 past videos per channel to populate the feed immediately
        for entry in feed.entries[:4]:
            video_id = entry.yt_videoid if hasattr(entry, 'yt_videoid') else entry.id.split(':')[-1]
            if video_id not in sent_videos:
                all_new_videos.append({
                    "channel_name": channel_name,
                    "video_id": video_id,
                    "title": entry.title,
                    "link": entry.link,
                    "published": entry.published_parsed if hasattr(entry, 'published_parsed') else None
                })

    all_new_videos = [v for v in all_new_videos if v["published"] is not None]
    all_new_videos.sort(key=lambda x: x["published"])

    # Limit to maximum 15 posts in a single execution to safely fill the channel right off the bat
    for video in all_new_videos[:15]:
        video_id = video["video_id"]
        channel_name = video["channel_name"]
        title_en = video["title"]
        link = video["link"]

        print(f"Processing video: {title_en} ({channel_name})")

        translated_title = translate_to_persian(title_en)

        escaped_translation = html.escape(translated_title)
        escaped_original = html.escape(title_en)
        escaped_channel = html.escape(channel_name)
        escaped_username = html.escape(CHANNEL_USERNAME)
        escaped_link = html.escape(link)

        RLM = "\u200f"
        safe_hashtag = escaped_channel.replace(" ", "_").replace("–", "").replace("—", "")

        # Try downloading the actual video, passing video_id directly
        video_path = download_youtube_video(link, video_id)
        
        video_sent = False
        
        if video_path and os.path.exists(video_path):
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            print(f"Downloaded video size: {file_size_mb:.2f} MB")
            
            # Standard Telegram Bot upload limit is strictly 50MB
            if file_size_mb <= 49.5:
                caption = (
                    f"{RLM}🎥 <b>مستند جدید کانال {escaped_channel}:</b>\n"
                    f"<blockquote>{RLM}{escaped_translation}</blockquote>\n\n"
                    f"{RLM}🇺🇸 <i>عنوان اصلی (جهت مشاهده ضربه بزنید):</i>\n"
                    f"<tg-spoiler>{escaped_original}</tg-spoiler>\n\n"
                    f"{RLM}🔗 <a href='{escaped_link}'>مشاهده ویدیو در یوتیوب</a>\n\n"
                    f"{RLM}#مستند #{safe_hashtag}\n"
                    f"{RLM}{escaped_username}\n"
                    f"{RLM}#youtube #YT"
                )
                print("Sending video file...")
                success = send_telegram_video(video_path, caption)
                if success:
                    save_sent_video(video_id)
                    video_sent = True
            else:
                print("Video exceeds 50MB limit. Falling back to thumbnail poster.")
                
            os.remove(video_path)
            
        # Fallback to high-resolution thumbnail if video is too large or download failed
        if not video_sent:
            print("Running fallback: sending high-resolution thumbnail poster instead...")
            caption = (
                f"{RLM}🎥 <b>مستند جدید کانال {escaped_channel}:</b>\n"
                f"<blockquote>{RLM}{escaped_translation}</blockquote>\n\n"
                f"{RLM}🇺🇸 <i>عنوان اصلی (جهت مشاهده ضربه بزنید):</i>\n"
                f"<tg-spoiler>{escaped_original}</tg-spoiler>\n\n"
                f"{RLM}🔗 <a href='{escaped_link}'>مشاهده ویدیو در یوتیوب</a>\n\n"
                f"{RLM}#مستند #{safe_hashtag}\n"
                f"{RLM}{escaped_username}\n"
                f"{RLM}#youtube #YT"
            )
            thumb_path = download_thumbnail(video_id)
            if thumb_path:
                success = send_telegram_photo(thumb_path, caption)
                if success:
                    save_sent_video(video_id)
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
        
        time.sleep(3)

if __name__ == "__main__":
    main()
