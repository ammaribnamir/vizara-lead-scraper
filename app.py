from datetime import datetime, timedelta, timezone
import gspread
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials
import streamlit as st

st.set_page_config(
    page_title="Vizara Media - Lead Scraper", page_icon="🚀", layout="wide"
)

st.title("🚀 Vizara Media - YouTube Lead Scraper")
st.subheader("Automated Lead Generation for Podcast & Creator Outreach")

# Setup Credentials from Streamlit Secrets
@st.cache_resource
def get_gspread_client():
  scope = [
      "https://spreadsheets.google.com/feeds",
      "https://www.googleapis.com/auth/drive",
  ]
  creds_dict = dict(st.secrets["gcp_service_account"])
  creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
  return gspread.authorize(creds)


# Sidebar Inputs & Controls
st.sidebar.header("⚙️ Configuration")
api_key = st.sidebar.text_input(
    "YouTube API Key",
    value=st.secrets.get("YOUTUBE_API_KEY", ""),
    type="password",
)
sheet_url = st.sidebar.text_input(
    "Google Sheet URL",
    value="https://docs.google.com/spreadsheets/d/1jtLtJDUoN_zQAytI3nWlnWdNO7iS7MAfSjy0fUcB3-M/edit",
)

st.sidebar.header("🎯 Lead Filters")
min_subs = st.sidebar.number_input(
    "Min Subscribers", value=10000, min_value=1000
)
max_subs = st.sidebar.number_input(
    "Max Subscribers", value=800000, min_value=1000
)
min_videos = st.sidebar.number_input(
    "Min Total Videos", value=50, min_value=1
)
recent_days = st.sidebar.number_input(
    "Uploaded Long-form Video Within (Days)", value=14, min_value=1
)

user_keywords = st.text_area(
    "Enter Keywords (separated by commas):",
    value="business podcast, startup founder podcast, real estate podcast, fitness coach podcast",
    height=100,
)

ALLOWED_COUNTRIES = {
    "US",
    "GB",
    "FR",
    "DE",
    "IT",
    "BE",
    "NL",
    "LU",
    "DK",
    "NO",
    "IS",
    "PT",
    "ES",
    "GR",
    "CA",
    "TR",
    "AU",
    "NZ",
    "JP",
    "SG",
    "CN",
    "RU",
    "PL",
}
BANNED_WORDS = [
    "music",
    "song",
    "sing",
    "singer",
    "christian",
    "christianity",
    "jesus",
    "church",
    "bible",
    "gospel",
    "alcohol",
    "wine",
    "beer",
    "whiskey",
    "vodka",
    "cocktail",
    "bar",
    "adultery",
    "sex",
    "erotic",
    "dance",
    "dancer",
    "dancing",
    "choreography",
]


def contains_banned_content(text):
  if not text:
    return False
  text_lower = text.lower()
  return any(word in text_lower for word in BANNED_WORDS)


def has_recent_longform_video(youtube, channel_id, days):
  cutoff_date = (
      datetime.now(timezone.utc) - timedelta(days=days)
  ).isoformat()
  search_response = (
      youtube.search()
      .list(
          channelId=channel_id,
          part="snippet",
          order="date",
          type="video",
          videoDuration="medium",
          publishedAfter=cutoff_date,
          maxResults=1,
      )
      .execute()
  )
  return len(search_response.get("items", [])) > 0


if st.button("🚀 Start Scraping & Sync to Google Sheets", type="primary"):
  if not api_key:
    st.error("Please provide a valid YouTube API key!")
  elif not user_keywords.strip():
    st.error("Please enter at least one keyword!")
  else:
    try:
      youtube = build("youtube", "v3", developerKey=api_key)
      client = get_gspread_client()
      sheet = client.open_by_url(sheet_url).sheet1

      # Initialize headers
      headers = [
          "Niche/Keyword",
          "Channel Name",
          "Subscribers",
          "Total Videos",
          "Country",
          "Channel URL",
          "Review Status",
      ]
      existing_records = sheet.get_all_values()
      if not existing_records:
        sheet.append_row(headers)

      keywords_list = [
          kw.strip() for kw in user_keywords.split(",") if kw.strip()
      ]
      all_leads = []

      for kw in keywords_list:
        st.write(f"🔍 Searching leads for: **{kw}**...")
        search_response = (
            youtube.search()
            .list(
                q=kw, type="video", part="snippet", order="date", maxResults=50
            )
            .execute()
        )
        channel_ids = list(
            set([
                item["snippet"]["channelId"]
                for item in search_response.get("items", [])
            ])
        )

        if not channel_ids:
          st.write(f"No results found for '{kw}'.")
          continue

        channels_response = (
            youtube.channels()
            .list(
                id=",".join(channel_ids),
                part="snippet,statistics,brandingSettings",
            )
            .execute()
        )

        kw_leads = []
        for channel in channels_response.get("items", []):
          channel_id = channel.get("id")
          snippet = channel.get("snippet", {})
          stats = channel.get("statistics", {})

          sub_count = int(stats.get("subscriberCount", 0))
          video_count = int(stats.get("videoCount", 0))
          country = snippet.get("country", "").upper()
          title = snippet.get("title", "")
          description = snippet.get("description", "")
          default_language = snippet.get("defaultLanguage", "").lower()

          combined_text = f"{title} {description}"

          if video_count < min_videos:
            continue
          if not (min_subs <= sub_count <= max_subs):
            continue
          if contains_banned_content(combined_text):
            continue
          if country and country not in ALLOWED_COUNTRIES:
            continue
          if default_language and not default_language.startswith("en"):
            continue
          if not has_recent_longform_video(youtube, channel_id, recent_days):
            continue

          channel_url = f"https://www.youtube.com/channel/{channel_id}"
          row = [
              kw,
              title,
              sub_count,
              video_count,
              country if country else "Not Specified",
              channel_url,
              "Pending Verification",
          ]
          kw_leads.append(row)

        if kw_leads:
          sheet.append_rows(kw_leads)
          all_leads.extend(kw_leads)
          st.success(
              f"✅ Added {len(kw_leads)} leads for '{kw}' to Google Sheet!"
          )
        else:
          st.info(f"No leads matched all strict filters for '{kw}'.")

      st.balloons()
      st.success(
          f"🎉 Done! Total {len(all_leads)} quality leads uploaded directly to"
          " your Google Sheet."
      )

    except Exception as e:
      st.error(f"Error: {str(e)}")
