import io
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

# ================= PAGE CONFIG =================
st.set_page_config(
    page_title="NCAA Fixtures Extraction Tool",
    page_icon="🏀",
    layout="wide"
)

st.title("🏀 NCAA Fixtures Extraction Tool")
st.caption("ESPN JSON API | Berlin (CET/CEST) and GMT/UTC time zones")

# ================= TIME ZONES =================
ET_TZ = ZoneInfo("America/New_York")
BERLIN_TZ = ZoneInfo("Europe/Berlin")
GMT_TZ = ZoneInfo("UTC")

# ================= HEADERS =================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NCAA-Fixture-Extractor/1.0)"
}

# ================= SPORT SLUG =================
SPORT_SLUG = {
    "Men": "mens-college-basketball",
    "Women": "womens-college-basketball"
}

# ================= OUTPUT COLUMNS =================
OUTPUT_COLUMNS = [
    "Start Date",
    "Start Time",
    "Description",
    "Date & Time (Berlin)",
    "Venue",
    "City",
    "Away Team",
    "Home Team",
    "Game URL"
]


# ================= CLEAN TEAM NAME =================
def clean_team_name(name: str) -> str:
    """Clean common ranking markers and whitespace from team names."""
    if not name:
        return ""
    return str(name).strip()


# ================= FETCH ESPN SCHEDULE =================
@st.cache_data(ttl=300, show_spinner=False)
def fetch_espn_schedule(et_date: str, sport_slug: str) -> pd.DataFrame:
    """
    Fetch NCAA basketball games for one US Eastern calendar date
    using ESPN's JSON scoreboard endpoint.
    """
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        f"basketball/{sport_slug}/scoreboard"
    )

    params = {
        "dates": et_date,
        "limit": 1000,
        "groups": 100
    }

    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()
    data = response.json()

    fixtures = []

    for event in data.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue

        competition = competitions[0]
        competitors = competition.get("competitors") or []

        home = ""
        away = ""
