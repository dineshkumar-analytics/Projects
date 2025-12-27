import requests
import pandas as pd
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import streamlit as st

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

SPORT_SLUG = {
    "Men's NCAA Basketball": "mens-college-basketball",
    "Women's NCAA Basketball": "womens-college-basketball"
}

BERLIN_TZ = ZoneInfo("Europe/Berlin")
ET_TZ = ZoneInfo("America/New_York")


def parse_time_to_berlin(date_str, time_str):
    try:
        dt_et = datetime.strptime(date_str + " " + time_str, "%Y%m%d %I:%M %p")
        dt_et = dt_et.replace(tzinfo=ET_TZ)
        dt_berlin = dt_et.astimezone(BERLIN_TZ)
        return dt_berlin.strftime("%Y-%m-%d %H:%M")
    except:
        return time_str


def fetch_espn_schedule(date, sport_slug):
    url = f"https://www.espn.com/{sport_slug}/schedule/_/date/{date}"
    response = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")

    fixtures = []

    tables = soup.select("table")

    for table in tables:
        rows = table.select("tbody tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            away = cols[0].get_text(" ", strip=True)
            home = cols[1].get_text(" ", strip=True)
            time_status = cols[2].get_text(" ", strip=True)

            location = ""
            if len(cols) >= 4:
                location = cols[3].get_text(" ", strip=True)

            if not away or not home:
                continue

            fixtures.append({
                "Date (ET)": date,
                "Away Team": away,
                "Home Team": home,
                "Time / Status (ET)": time_status,
                "Time (Berlin)": parse_time_to_berlin(date, time_status),
                "Location": location
            })

    return pd.DataFrame(fixtures)


def extract_schedule_range(start_date, end_date, sport_slug):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    all_data = []
    current = start

    progress = st.progress(0)
    day_count = (end - start).days + 1

    for i in range(day_count):
        date_str = current.strftime("%Y%m%d")

        df = fetch_espn_schedule(date_str, sport_slug)

        if not df.empty:
            all_data.append(df)

        current += timedelta(days=1)
        progress.progress((i + 1) / day_count)
        time.sleep(1.2)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()


# -------- STREAMLIT UI --------

st.title("🏀 NCAA Basketball Fixtures (ESPN)")
st.write("Men's & Women's • ET → Berlin • Includes Location")

sport_choice = st.selectbox(
    "Competition",
    ["Men's NCAA Basketball", "Women's NCAA Basketball"]
)

start_date = st.date_input("Start Date")
end_date = st.date_input("End Date")

if st.button("Fetch Fixtures"):
    if start_date > end_date:
        st.error("Start date must be before end date")
    else:
        with st.spinner("Fetching schedule..."):
            df = extract_schedule_range(
                str(start_date),
                str(end_date),
                SPORT_SLUG[sport_choice]
            )

        if df.empty:
            st.warning("No fixtures found for this date range.")
        else:
            st.success(f"Found {len(df)} fixtures")
            st.dataframe(df)

            excel_file = "ncaa_fixtures.xlsx"
            df.to_excel(excel_file, index=False)

            with open(excel_file, "rb") as f:
                st.download_button(
                    label="📥 Download Excel",
                    data=f,
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
