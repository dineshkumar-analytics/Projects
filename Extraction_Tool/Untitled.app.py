import requests
import pandas as pd
import time
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

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

    # Ignore non-playable statuses
    if any(x in txt for x in ["final", "tbd", "post", "ppd", "canceled"]):
        return pd.NaT, pd.NaT

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
        return pd.NaT, pd.NaT

# ================= VENUE FETCH =================
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
            f"basketball/{sport_slug}/summary"
            f"?event={event_id}"
        )

        r = requests.get(api_url, headers=HEADERS, timeout=30)
        data = r.json()

        venue = data.get("gameInfo", {}).get("venue", {})
        address = venue.get("address", {})

        venue_name = venue.get("fullName", "").strip()
        city = address.get("city", "").strip()

        return venue_name, city

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

        # Game URL
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

        time.sleep(0.25)

    return pd.DataFrame(fixtures)

# ================= RANGE EXTRACTION =================
def extract_fixtures_by_berlin_range(start_date, end_date, sport, output_file):
    sport_slug = SPORT_SLUG[sport]

    berlin_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
    berlin_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)

    all_results = []
    current_day = berlin_start

    while current_day <= berlin_end:
        berlin_day_start = current_day
        berlin_day_end = current_day + timedelta(days=1)

        et_dates = {
            berlin_day_start.astimezone(ET_TZ).strftime("%Y%m%d"),
            berlin_day_end.astimezone(ET_TZ).strftime("%Y%m%d")
        }

        day_data = []

        for et_date in sorted(et_dates):
            print(f"📅 Fetching ET schedule: {et_date}")
            df = fetch_espn_schedule_by_et_date(et_date, sport_slug)
            if not df.empty:
                day_data.append(df)

        if day_data:
            df_all = pd.concat(day_data, ignore_index=True)

            # 🔥 FIX: Ensure datetime format
            df_all["Berlin DateTime"] = pd.to_datetime(df_all["Berlin DateTime"], errors="coerce")

            df_filtered = df_all[
                df_all["Berlin DateTime"].notna() &
                (df_all["Berlin DateTime"].dt.date == berlin_day_start.date())
            ].copy()

            all_results.append(df_filtered)

        current_day += timedelta(days=1)

    if not all_results:
        print("❌ No fixtures found")
        return pd.DataFrame()

    df_final = pd.concat(all_results, ignore_index=True)

    # 🔥 Ensure GMT datetime also safe
    df_final["GMT DateTime"] = pd.to_datetime(df_final["GMT DateTime"], errors="coerce")

    # ================= FINAL FORMAT =================
    df_final["Start Date"] = df_final["GMT DateTime"].dt.strftime("%m/%d/%Y")
    df_final["Start Time"] = df_final["GMT DateTime"].dt.strftime("%I:%M:%S %p")

    df_final["Description"] = df_final["Home Team"] + " v " + df_final["Away Team"]

    df_final["Date & Time (Berlin)"] = df_final["Berlin DateTime"].dt.strftime("%Y-%m-%d %H:%M %Z")

    df_final.drop(columns=["Berlin DateTime", "GMT DateTime"], inplace=True)

    df_final = df_final[[
        "Away Team",
        "Home Team",
        "Venue",
        "City",
        "Game URL",
        "Start Date",
        "Start Time",
        "Description",
        "Date & Time (Berlin)"
    ]]

    df_final.to_excel(output_file, index=False)
    print(f"\n✅ Excel created: {output_file}")

    return df_final

# ================= RUN =================
if __name__ == "__main__":
    extract_fixtures_by_berlin_range(
        start_date="2026-01-22",
        end_date="2026-01-22",
        sport="Women",
        output_file="NCAA_Fixtures_Final.xlsx"
    )
