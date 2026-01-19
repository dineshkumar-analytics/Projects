import streamlit as st
import requests
import pandas as pd
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import tempfile
import os

# ================= PAGE CONFIG =================
st.set_page_config(
    page_title="NCAA Fixture Extraction Tool",
    layout="wide"
)

st.title("NCAA Fixture Extraction Tool")
st.caption("Berlin (CET/CEST) & GMT time zones | ESPN Schedule Extraction")

# ================= TIME ZONES =================
ET_TZ = ZoneInfo("America/New_York")
BERLIN_TZ = ZoneInfo("Europe/Berlin")
GMT_TZ = ZoneInfo("UTC")

# ================= HEADERS =================
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ================= SPORT SLUG =================
SPORT_SLUG = {
    "Men": "mens-college-basketball",
    "Women": "womens-college-basketball"
}

# ================= TEAM NAME CLEAN =================
def clean_team_name(name: str) -> str:
    name = re.sub(r'@', '', name)
    name = re.sub(r'^\s*\d+\s*[-–]?\s*', '', name)
    return name.strip()

# ================= TIME CONVERSION =================
def convert_et_to_timezones(et_date, time_str):
    txt = time_str.lower()
    if any(x in txt for x in ["final", "tbd", "post", "ppd"]):
        return None, None

    try:
        dt_et = datetime.strptime(
            f"{et_date} {time_str}",
            "%Y%m%d %I:%M %p"
        ).replace(tzinfo=ET_TZ)

        return (
            dt_et.astimezone(BERLIN_TZ),
            dt_et.astimezone(GMT_TZ)
        )
    except Exception:
        return None, None

# ================= VENUE FETCH =================
def fetch_venue(game_url):
    if not game_url:
        return "", ""

    try:
        m = re.search(r'gameId/(\d+)', game_url)
        if not m:
            return "", ""

        event_id = m.group(1)
        api_url = (
            "https://site.web.api.espn.com/apis/site/v2/sports/"
            "basketball/mens-college-basketball/summary"
            f"?event={event_id}"
        )

        r = requests.get(api_url, headers=HEADERS, timeout=30)
        data = r.json()

        venue = data.get("gameInfo", {}).get("venue", {})
        address = venue.get("address", {})

        return venue.get("fullName", ""), address.get("city", "")

    except Exception:
        return "", ""

# ================= FETCH ESPN =================
def fetch_espn_schedule_by_et_date(et_date, sport_slug):
    url = f"https://www.espn.com/{sport_slug}/schedule/_/date/{et_date}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")

    rows = soup.select("table tbody tr")
    fixtures = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        away = clean_team_name(cols[0].get_text(strip=True))
        home = clean_team_name(cols[1].get_text(strip=True))
        time_status = cols[2].get_text(strip=True)

        game_url = ""
        for a in row.find_all("a", href=True):
            if "gameId" in a["href"]:
                game_url = (
                    "https://www.espn.com" + a["href"]
                    if a["href"].startswith("/")
                    else a["href"]
                )
                break

        berlin_dt, gmt_dt = convert_et_to_timezones(et_date, time_status)
        venue, city = fetch_venue(game_url)

        fixtures.append({
            "Away Team": away,
            "Home Team": home,
            "Berlin DateTime": berlin_dt,
            "GMT DateTime": gmt_dt,
            "Venue": venue,
            "City": city,
            "Game URL": game_url
        })

        time.sleep(0.2)

    return pd.DataFrame(fixtures)

# ================= EXTRACTION =================
def extract_fixtures_by_berlin_date(berlin_date, sport):
    sport_slug = SPORT_SLUG[sport]

    berlin_start = datetime.strptime(
        berlin_date, "%Y-%m-%d"
    ).replace(tzinfo=BERLIN_TZ)

    berlin_end = berlin_start + timedelta(days=1)

    et_dates = {
        berlin_start.astimezone(ET_TZ).strftime("%Y%m%d"),
        berlin_end.astimezone(ET_TZ).strftime("%Y%m%d")
    }

    all_data = []

    for et_date in sorted(et_dates):
        df = fetch_espn_schedule_by_et_date(et_date, sport_slug)
        if not df.empty:
            all_data.append(df)

    if not all_data:
        return pd.DataFrame()

    df_all = pd.concat(all_data, ignore_index=True)

    df_final = df_all[
        df_all["Berlin DateTime"].notna() &
        (df_all["Berlin DateTime"].dt.date == berlin_start.date())
    ].copy()

    df_final["Start Date"] = df_final["GMT DateTime"].dt.strftime("%m/%d/%Y")
    df_final["Start Time"] = df_final["GMT DateTime"].dt.strftime("%I:%M:%S %p")

    df_final["Description"] = (
        df_final["Home Team"] + " v " + df_final["Away Team"]
    )

    df_final["Date & Time (Berlin)"] = (
        df_final["Berlin DateTime"].dt.strftime("%Y-%m-%d %H:%M %Z")
    )

    df_final.drop(
        columns=["Berlin DateTime", "GMT DateTime"],
        inplace=True
    )

    return df_final

# ================= UI CONTROLS =================
col1, col2 = st.columns(2)

with col1:
    berlin_date = st.date_input("Select Berlin Date")

with col2:
    sport = st.selectbox("Select Sport", ["Men", "Women"])

# ================= RUN BUTTON =================
if st.button("Extract Fixtures"):
    with st.spinner("Extracting fixtures from ESPN..."):
        df = extract_fixtures_by_berlin_date(
            berlin_date.strftime("%Y-%m-%d"),
            sport
        )

    if df.empty:
        st.warning("No fixtures found for the selected date.")
    else:
        st.success(f"Fixtures extracted: {len(df)}")

        st.subheader("Fixture Preview")
        st.dataframe(df, use_container_width=True)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            output_path = tmp.name

        df.to_excel(output_path, index=False)

        with open(output_path, "rb") as f:
            st.download_button(
                "Download Excel",
                f,
                file_name="NCAA_Fixtures_Final.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        os.remove(output_path)
