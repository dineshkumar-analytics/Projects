import streamlit as st
import requests
import pandas as pd
import time
from bs4 import BeautifulSoup
from io import BytesIO
from datetime import datetime, timedelta

# ---------- TIME ZONE ----------
try:
    from zoneinfo import ZoneInfo
    ET_TZ = ZoneInfo("America/New_York")
    BERLIN_TZ = ZoneInfo("Europe/Berlin")
except Exception:
    ET_TZ = BERLIN_TZ = None

# ---------- HEADERS ----------
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ---------- SPORT SLUG ----------
SPORT_SLUG = {
    "Men": "mens-college-basketball",
    "Women": "womens-college-basketball"
}


def parse_time_to_berlin(date_str, time_str):
    if ET_TZ is None or BERLIN_TZ is None:
        return time_str

    txt = time_str.lower()
    if any(x in txt for x in ["final", "tbd", "post", "ppd"]):
        return time_str

    try:
        dt_et = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %I:%M %p")
        dt_et = dt_et.replace(tzinfo=ET_TZ)
        dt_berlin = dt_et.astimezone(BERLIN_TZ)
        return dt_berlin.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return time_str


def fetch_venue_from_api(game_url):
    if not game_url:
        return ""

    try:
        import re
        m = re.search(r'gameId/(\d+)', game_url)
        if not m:
            return ""

        event_id = m.group(1)

        api_url = f"https://site.web.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={event_id}"

        r = requests.get(api_url, headers=HEADERS, timeout=30)
        data = r.json()

        venue = data.get("gameInfo", {}).get("venue", {})

        name = venue.get("fullName", "")
        addr = venue.get("address", {})

        city = addr.get("city", "")
        state = addr.get("state", "")
        country = addr.get("country", "")

        parts = [p for p in [name, city, state, country] if p]
        return ", ".join(parts)

    except Exception:
        return ""


def fetch_venue_html(game_url):
    try:
        r = requests.get(game_url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")

        el = soup.find("span", attrs={"data-testid": "game-location"})
        if el:
            return el.get_text(" ", strip=True)

    except Exception:
        pass

    return ""


def fetch_venue(game_url):
    venue = fetch_venue_from_api(game_url)
    if not venue:
        venue = fetch_venue_html(game_url)
    return venue


def fetch_espn_schedule(date, sport_slug):
    url = f"https://www.espn.com/{sport_slug}/schedule/_/date/{date}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")

    rows = soup.select("table tbody tr")
    if not rows:
        return pd.DataFrame()

    fixtures = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        away = cols[0].get_text(" ", strip=True)
        home = cols[1].get_text(" ", strip=True)
        time_status = cols[2].get_text(" ", strip=True)

        if not away or not home:
            continue

        # Game URL
        game_url = ""
        for a in row.find_all("a", href=True):
            if "gameId" in a["href"]:
                href = a["href"]
                if href.startswith("/"):
                    href = "https://www.espn.com" + href
                game_url = href
                break

        # Venue
        venue = fetch_venue(game_url)
        time.sleep(0.2)

        fixtures.append({
            "Date (ET)": date,
            "Away Team": away,
            "Home Team": home,
            "Time / Status (ET)": time_status,
            "Time (Berlin)": parse_time_to_berlin(date, time_status),
            "Venue": venue,
            "Game URL": game_url
        })

    return pd.DataFrame(fixtures)


def extract_schedule(start_date, end_date, sport):
    sport_slug = SPORT_SLUG[sport]

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    all_data = []
    current = start

    total_days = (end - start).days + 1
    progress = st.progress(0)
    step = 0

    while current <= end:
        date_str = current.strftime("%Y%m%d")

        with st.spinner(f"Fetching {date_str} ({sport})"):
            df = fetch_espn_schedule(date_str, sport_slug)

        if not df.empty:
            all_data.append(df)

        step += 1
        progress.progress(step / total_days)

        time.sleep(0.5)
        current += timedelta(days=1)

    if not all_data:
        return pd.DataFrame()

    return pd.concat(all_data, ignore_index=True)


def to_excel(df):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Schedule")
    buffer.seek(0)
    return buffer


# ---------- STREAMLIT UI ----------

st.title("🏀 NCAA ESPN Schedule Extractor (with Venue)")
st.write("Extract fixtures from ESPN **date-wise schedule pages** including venue.")

sport = st.selectbox("Select Competition", ["Men", "Women"])

col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date")
with col2:
    end_date = st.date_input("End Date")

if st.button("Extract Fixtures"):
    if start_date > end_date:
        st.error("Start date must be before end date.")
    else:
        df = extract_schedule(str(start_date), str(end_date), sport)

        if df.empty:
            st.warning("No fixtures found for this range.")
        else:
            st.success(f"Extracted {len(df)} fixtures ✔")

            st.dataframe(df, use_container_width=True)

            excel_file = to_excel(df)

            st.download_button(
                label="📥 Download Excel",
                data=excel_file,
                file_name=f"NCAA_{sport}_Fixtures_With_Venue.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
