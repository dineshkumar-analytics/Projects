import requests
import pandas as pd
import time
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import streamlit as st
from bs4 import BeautifulSoup

# ================= TIME ZONES =================
ET_TZ = ZoneInfo("America/New_York")
BERLIN_TZ = ZoneInfo("Europe/Berlin")
GMT_TZ = ZoneInfo("UTC")

# ================= HEADERS =================
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ================= SPORT SLUG =================
SPORT_SLUG = {
    "Men": "mens-college-basketball",
    "Women": "womens-college-basketball"
}

# ================= CLEAN TEAM NAME =================
def clean_team_name(name: str) -> str:
    name = re.sub(r'@', '', name)
    name = re.sub(r'^\s*\d+\s*[-–]?\s*', '', name)
    return name.strip()

# ================= TIME CONVERSION =================
def convert_et_to_timezones(et_date, time_str):
    txt = time_str.lower()

    if any(x in txt for x in ["final", "tbd", "post", "ppd", "canceled"]):
        return pd.NaT, pd.NaT   # ✅ FIX

    try:
        dt_et = datetime.strptime(
            f"{et_date} {time_str}",
            "%Y%m%d %I:%M %p"
        ).replace(tzinfo=ET_TZ)

        return (
            dt_et.astimezone(BERLIN_TZ),
            dt_et.astimezone(GMT_TZ)
        )
    except:
        return pd.NaT, pd.NaT   # ✅ FIX

# ================= FETCH VENUE =================
def fetch_venue(game_url, sport_slug):
    if not game_url:
        return "", ""

    try:
        m = re.search(r'gameId/(\d+)', game_url)
        if not m:
            return "", ""

        event_id = m.group(1)

        api_url = (
            "https://site.web.api.espn.com/apis/site/v2/sports/"
            f"basketball/{sport_slug}/summary?event={event_id}"
        )

        r = requests.get(api_url, headers=HEADERS, timeout=30)
        data = r.json()

        venue = data.get("gameInfo", {}).get("venue", {})
        address = venue.get("address", {})

        return (
            venue.get("fullName", "").strip(),
            address.get("city", "").strip()
        )
    except:
        return "", ""

# ================= FETCH ESPN =================
def fetch_espn_schedule(et_date, sport_slug):
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
                    if a["href"].startswith("/") else a["href"]
                )
                break

        berlin_dt, gmt_dt = convert_et_to_timezones(et_date, time_status)
        venue, city = fetch_venue(game_url, sport_slug)

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

# ================= MAIN LOGIC =================
def extract_data(start_date, end_date, sport):
    sport_slug = SPORT_SLUG[sport]

    berlin_start = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=BERLIN_TZ)
    berlin_end = datetime.combine(end_date, datetime.min.time()).replace(tzinfo=BERLIN_TZ)

    all_results = []
    current_day = berlin_start

    while current_day <= berlin_end:
        et_dates = {
            current_day.astimezone(ET_TZ).strftime("%Y%m%d"),
            (current_day + timedelta(days=1)).astimezone(ET_TZ).strftime("%Y%m%d")
        }

        temp = []

        for et_date in et_dates:
            df = fetch_espn_schedule(et_date, sport_slug)
            if not df.empty:
                temp.append(df)

        if temp:
            df_all = pd.concat(temp, ignore_index=True)

            # ✅ CRITICAL FIX
            df_all["Berlin DateTime"] = pd.to_datetime(
                df_all["Berlin DateTime"], errors="coerce"
            )

            df_filtered = df_all[
                df_all["Berlin DateTime"].notna() &
                (df_all["Berlin DateTime"].dt.date == current_day.date())
            ]

            all_results.append(df_filtered)

        current_day += timedelta(days=1)

    if not all_results:
        return pd.DataFrame()

    df_final = pd.concat(all_results, ignore_index=True)

    # ✅ Ensure GMT datetime safe
    df_final["GMT DateTime"] = pd.to_datetime(
        df_final["GMT DateTime"], errors="coerce"
    )

    df_final["Start Date"] = df_final["GMT DateTime"].dt.strftime("%m/%d/%Y")
    df_final["Start Time"] = df_final["GMT DateTime"].dt.strftime("%I:%M:%S %p")
    df_final["Description"] = df_final["Home Team"] + " vs " + df_final["Away Team"]

    return df_final

# ================= STREAMLIT UI =================
st.title("🏀 NCAA Fixtures Extraction Tool")

sport = st.selectbox("Select Sport", ["Men", "Women"])
start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

if st.button("Extract Fixtures"):
    with st.spinner("Fetching data..."):
        df = extract_data(start_date, end_date, sport)

    if df.empty:
        st.error("No data found ❌")
    else:
        st.success("Data fetched successfully ✅")
        st.dataframe(df)

        csv = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download CSV",
            data=csv,
            file_name="fixtures.csv",
            mime="text/csv"
        )
