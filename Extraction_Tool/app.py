import requests
import pandas as pd
import streamlit as st
import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

# ================= PAGE CONFIG =================
st.set_page_config(
    page_title="NCAA Fixture Extraction Tool",
    page_icon="🏀",
    layout="wide"
)

st.title("🏀 NCAA Fixtures Extraction Tool")
st.caption("ESPN JSON API | Berlin (CET/CEST) and GMT/UTC time zones")

# ================= TIME ZONES =================
ET_TZ = ZoneInfo("America/New_York")
BERLIN_TZ = ZoneInfo("Europe/Berlin")
GMT_TZ = ZoneInfo("UTC")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NCAAFixtureExtractor/1.0)"
}

SPORT_SLUG = {
    "Men": "mens-college-basketball",
    "Women": "womens-college-basketball"
}

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


# ================= FETCH ESPN SCHEDULE =================
@st.cache_data(ttl=300, show_spinner=False)
def fetch_espn_schedule_by_et_date(et_date: str, sport_slug: str):
    """
    Fetch events for one US Eastern calendar date from ESPN's
    scoreboard JSON endpoint.
    """
    api_url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        f"basketball/{sport_slug}/scoreboard"
    )

    params = {
        "dates": et_date,
        "limit": 1000,
        "groups": 100
    }

    response = requests.get(
        api_url,
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

        for competitor in competitors:
            team_info = competitor.get("team") or {}
            team_name = (
                team_info.get("displayName")
                or team_info.get("name")
                or team_info.get("shortDisplayName")
                or ""
            ).strip()

            if competitor.get("homeAway") == "home":
                home = team_name
            elif competitor.get("homeAway") == "away":
                away = team_name

        if not home or not away:
            continue

        event_date = event.get("date") or competition.get("date")
        if not event_date:
            continue

        dt_utc = pd.to_datetime(
            event_date, utc=True, errors="coerce"
        )
        if pd.isna(dt_utc):
            continue

        dt_berlin = dt_utc.tz_convert(BERLIN_TZ)

        venue_info = competition.get("venue") or {}
        address = venue_info.get("address") or {}
        event_id = str(event.get("id") or "").strip()

        game_url = (
            f"https://www.espn.com/{sport_slug}/game/_/gameId/{event_id}"
            if event_id
            else ""
        )

        fixtures.append({
            "Away Team": away,
            "Home Team": home,
            "Berlin DateTime": dt_berlin,
            "GMT DateTime": dt_utc,
            "Venue": venue_info.get("fullName", ""),
            "City": address.get("city", ""),
            "Game URL": game_url
        })

    return pd.DataFrame(
        fixtures,
        columns=[
            "Away Team",
            "Home Team",
            "Berlin DateTime",
            "GMT DateTime",
            "Venue",
            "City",
            "Game URL"
        ]
    )


# ================= EXTRACT BERLIN DATE RANGE =================
def extract_fixtures_by_berlin_range(
    start_date: date,
    end_date: date,
    sport: str
) -> pd.DataFrame:
    """
    Extract games whose scheduled kickoff falls within the selected
    Berlin calendar dates. Queries both relevant US Eastern dates
    to cover the Berlin/US time-zone difference.
    """
    sport_slug = SPORT_SLUG[sport]
    all_results = []

    current_day = start_date

    while current_day <= end_date:
        berlin_start = datetime.combine(
            current_day, datetime.min.time(), tzinfo=BERLIN_TZ
        )
        berlin_end = berlin_start + timedelta(days=1)

        # Query the Eastern date at the start and just before
        # the end of this Berlin calendar day.
        et_dates = sorted({
            berlin_start.astimezone(ET_TZ).strftime("%Y%m%d"),
            (berlin_end - timedelta(seconds=1))
            .astimezone(ET_TZ).strftime("%Y%m%d")
        })

        day_results = []

        for et_date in et_dates:
            df = fetch_espn_schedule_by_et_date(et_date, sport_slug)
            if not df.empty:
                day_results.append(df)
            time.sleep(0.15)

        if day_results:
            df_day = pd.concat(day_results, ignore_index=True)

            # Normalize timestamps to UTC before filtering.
            df_day["GMT DateTime"] = pd.to_datetime(
                df_day["GMT DateTime"], utc=True, errors="coerce"
            )
            df_day = df_day.dropna(subset=["GMT DateTime"]).copy()

            df_day["Berlin DateTime"] = (
                df_day["GMT DateTime"].dt.tz_convert(BERLIN_TZ)
            )

            start_ts = pd.Timestamp(berlin_start)
            end_ts = pd.Timestamp(berlin_end)

            df_day = df_day[
                (df_day["Berlin DateTime"] >= start_ts)
                & (df_day["Berlin DateTime"] < end_ts)
            ].copy()

            if not df_day.empty:
                all_results.append(df_day)

        current_day += timedelta(days=1)

    if not all_results:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df_final = pd.concat(all_results, ignore_index=True)

    # Prefer ESPN event ID in the Game URL to identify duplicate games.
    df_final = df_final.drop_duplicates(
        subset=["Game URL"], keep="first"
    )
    # If a URL is unavailable, deduplicate by teams and kickoff time.
    missing_url = df_final["Game URL"].fillna("").eq("")
    if missing_url.any():
        with_url = df_final[~missing_url]
        without_url = df_final[missing_url].drop_duplicates(
            subset=["Home Team", "Away Team", "GMT DateTime"],
            keep="first"
        )
        df_final = pd.concat([with_url, without_url], ignore_index=True)

    df_final["Start Date"] = (
        df_final["GMT DateTime"].dt.strftime("%m/%d/%Y")
    )
    df_final["Start Time"] = (
        df_final["GMT DateTime"].dt.strftime("%I:%M:%S %p")
    )
    df_final["Description"] = (
        df_final["Home Team"] + " v " + df_final["Away Team"]
    )
    df_final["Date & Time (Berlin)"] = (
        df_final["Berlin DateTime"].dt.strftime("%Y-%m-%d %H:%M %Z")
    )

    df_final = df_final.reindex(columns=OUTPUT_COLUMNS)
    df_final = df_final.sort_values(
        by=["Start Date", "Start Time"],
        kind="stable",
        na_position="last"
    ).reset_index(drop=True)

    return df_final


# ================= STREAMLIT UI =================
today = date.today()
default_end = today + timedelta(days=7)

col1, col2, col3 = st.columns(3)

with col1:
    start_date = st.date_input(
        "Start Date (Berlin)",
        value=today
    )

with col2:
    end_date = st.date_input(
        "End Date (Berlin)",
        value=default_end
    )

with col3:
    sport = st.selectbox("Select Sport", ["Men", "Women"])

if st.button("Extract Fixtures", type="primary"):
    if start_date > end_date:
        st.error("Start date must be before or equal to end date.")
    elif (end_date - start_date).days > 90:
        st.error("Please select a date range of 90 days or fewer per extraction.")
    else:
        try:
            with st.spinner("Fetching fixtures from ESPN..."):
                df = extract_fixtures_by_berlin_range(
                    start_date, end_date, sport
                )

            if df.empty:
                st.warning(
                    "No fixtures were returned for this date range. "
                    "The schedule may not be published yet, or ESPN may "
                    "not have returned events for the selected dates. "
                    "Try a different date range and check the ESPN API."
                )
            else:
                st.success(f"Fixtures extracted: {len(df)}")
                st.dataframe(df, use_container_width=True)

                excel_buffer = __import__("io").BytesIO()
                with pd.ExcelWriter(
                    excel_buffer, engine="openpyxl"
                ) as writer:
                    df.to_excel(
                        writer, index=False, sheet_name="Fixtures"
                    )

                st.download_button(
                    label="Download Excel",
                    data=excel_buffer.getvalue(),
                    file_name="NCAA_Fixtures_Final.xlsx",
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    )
                )

                csv_data = df.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    label="Download CSV",
                    data=csv_data,
                    file_name="NCAA_Fixtures_Final.csv",
                    mime="text/csv"
                )

        except requests.RequestException as exc:
            st.error(
                "Unable to fetch data from ESPN. "
                f"Please retry later. Details: {exc}"
            )
        except (ValueError, KeyError) as exc:
            st.error(
                "ESPN returned unexpected schedule data. "
                f"Details: {exc}"
            )
