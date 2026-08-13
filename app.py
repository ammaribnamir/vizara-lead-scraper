import streamlit as st
import googleapiclient.discovery
import googleapiclient.errors
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import datetime
import re
import isodate
import json

st.set_page_config(page_title="Vizara Media - Lead Scraper", page_icon="🚀", layout="wide")

st.markdown("""
    <style>
    .main-header { font-size: 32px; font-weight: bold; color: #1E88E5; }
    .sub-header { font-size: 18px; color: #555555; }
    .stButton>button { background-color: #FF0000; color: white; font-weight: bold; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🚀 Vizara Media - YouTube Lead Scraper</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Automated Lead Generation for Podcast & Creator Outreach</div><br>', unsafe_allow_html=True)

# Sidebar Configuration
st.sidebar.header("⚙️ Configuration")

default_api_key = st.secrets.get("YOUTUBE_API_KEY", "")
api_key = st.sidebar.text_input("YouTube API Key", value=default_api_key, type="password")

sheet_url = st.sidebar.text_input(
    "Google Sheet URL",
    value="https://docs.google.com/spreadsheets/d/1jtLtJDUoN_zQAytI3nWlnWdNO7iS7MAfSjy0fUcB3-M/edit?gid=0#gid=0"
)

st.sidebar.header("🎯 Lead Filters")
min_subs = st.sidebar.number_input("Min Subscribers", value=10000, step=1000)
max_subs = st.sidebar.number_input("Max Subscribers", value=800000, step=10000)
min_total_videos = st.sidebar.number_input("Min Total Videos", value=50, step=5)
uploaded_within_days = st.sidebar.number_input("Uploaded Long-form Video Within (Days)", value=14, step=1)

keywords_input = st.text_area(
    "Enter Keywords (separated by commas):",
    value="business podcast, real estate podcast, fitness coach",
    height=100
)

def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
    elif "GCP_JSON" in st.secrets:
        creds_dict = json.loads(st.secrets["GCP_JSON"], strict=False)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        st.error("No Google Credentials found in Secrets.")
        return None
    return gspread.authorize(creds)

def ensure_clean_headers(worksheet):
    headers = [
        "Channel ID", "Channel Name", "Channel URL", 
        "Subscribers", "Total Videos", "Last Upload Date", 
        "Extracted Emails", "Social Links", "Source Keyword", "Scraped Date"
    ]
    try:
        existing = worksheet.get_all_values()
        if not existing:
            worksheet.append_row(headers)
            worksheet.format("A1:J1", {
                "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                "backgroundColor": {"red": 0.12, "green": 0.53, "blue": 0.90},
                "horizontalAlignment": "CENTER"
            })
        elif existing[0] != headers:
            worksheet.insert_row(headers, index=1)
            worksheet.format("A1:J1", {
                "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                "backgroundColor": {"red": 0.12, "green": 0.53, "blue": 0.90},
                "horizontalAlignment": "CENTER"
            })
    except Exception:
        pass

def extract_emails(text):
    if not text:
        return "N/A"
    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_regex, text)
    return ", ".join(list(set(emails))) if emails else "N/A"

def extract_socials(text):
    if not text:
        return "N/A"
    social_domains = ['instagram.com', 'twitter.com', 'x.com', 'linkedin.com', 'facebook.com', 'tiktok.com']
    found = []
    for line in text.split():
        for domain in social_domains:
            if domain in line.lower():
                found.append(line.strip())
    return ", ".join(list(set(found))) if found else "N/A"

def run_scraper():
    if not api_key:
        st.error("Please provide a valid YouTube API Key.")
        return

    try:
        gc = get_gspread_client()
        if not gc:
            return
        sh = gc.open_by_url(sheet_url)
        worksheet = sh.sheet1
        ensure_clean_headers(worksheet)
    except Exception as e:
        st.error(f"Failed to connect to Google Sheet: {e}")
        return

    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)
    keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
    
    st.info(f"Scanning for keywords: {', '.join(keywords)}")

    existing_channel_ids = set()
    try:
        existing_records = worksheet.get_all_records()
        for rec in existing_records:
            if "Channel ID" in rec:
                existing_channel_ids.add(str(rec["Channel ID"]))
    except Exception:
        pass

    leads_added = 0
    now = datetime.datetime.now(datetime.timezone.utc)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for idx, kw in enumerate(keywords):
        status_text.text(f"Searching for '{kw}'...")
        progress_bar.progress((idx) / len(keywords))

        try:
            search_response = youtube.search().list(
                q=kw,
                type="channel",
                part="snippet",
                maxResults=25
            ).execute()

            channel_ids = [item["snippet"]["channelId"] for item in search_response.get("items", [])]

            if not channel_ids:
                continue

            channels_response = youtube.channels().list(
                id=",".join(channel_ids),
                part="snippet,statistics,contentDetails"
            ).execute()

            for item in channels_response.get("items", []):
                c_id = item["id"]

                if c_id in existing_channel_ids:
                    continue

                stats = item.get("statistics", {})
                subs = int(stats.get("subscriberCount", 0))
                video_count = int(stats.get("videoCount", 0))

                if not (min_subs <= subs <= max_subs):
                    continue
                if video_count < min_total_videos:
                    continue

                uploads_playlist_id = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                if not uploads_playlist_id:
                    continue

                playlist_response = youtube.playlistItems().list(
                    playlistId=uploads_playlist_id,
                    part="snippet",
                    maxResults=10
                ).execute()

                recent_videos = playlist_response.get("items", [])
                if not recent_videos:
                    continue

                recent_video_ids = [v["snippet"]["resourceId"]["videoId"] for v in recent_videos]
                video_details = youtube.videos().list(
                    id=",".join(recent_video_ids),
                    part="contentDetails,snippet"
                ).execute()

                has_recent_longform = False
                latest_upload_date = None

                for v in video_details.get("items", []):
                    pub_at_str = v["snippet"]["publishedAt"]
                    pub_at = datetime.datetime.fromisoformat(pub_at_str.replace("Z", "+00:00"))

                    if not latest_upload_date or pub_at > latest_upload_date:
                        latest_upload_date = pub_at

                    duration_iso = v.get("contentDetails", {}).get("duration", "")
                    if not duration_iso:
                        continue

                    try:
                        duration_sec = isodate.parse_duration(duration_iso).total_seconds()
                    except Exception:
                        duration_sec = 0

                    days_old = (now - pub_at).days
                    if days_old <= uploaded_within_days and duration_sec >= 120:
                        has_recent_longform = True
                        break

                if not has_recent_longform:
                    continue

                snippet = item["snippet"]
                title = snippet.get("title", "")
                description = snippet.get("description", "")
                custom_url = snippet.get("customUrl", "")

                channel_url = f"https://www.youtube.com/{custom_url}" if custom_url else f"https://www.youtube.com/channel/{c_id}"
                emails = extract_emails(description)
                socials = extract_socials(description)

                row = [
                    c_id,
                    title,
                    channel_url,
                    subs,
                    video_count,
                    latest_upload_date.strftime("%Y-%m-%d") if latest_upload_date else "N/A",
                    emails,
                    socials,
                    kw,
                    now.strftime("%Y-%m-%d %H:%M:%S")
                ]

                worksheet.append_row(row)
                existing_channel_ids.add(c_id)
                leads_added += 1

        except Exception as err:
            st.warning(f"Error processing keyword '{kw}': {err}")

    progress_bar.progress(1.0)
    status_text.text("Completed!")
    st.success(f"Done! Successfully scraped and added {leads_added} new qualified leads to your Google Sheet.")
    st.balloons()

if st.button("🚀 Start Scraping & Sync to Google Sheets"):
    run_scraper()
