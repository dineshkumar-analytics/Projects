import io
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st


# ============================================================
# ESPN NCAA BASKETBALL SCHEDULE EXTRACTOR
# Uses ESPN's SCHEDULE-PAGE endpoint, not the scoreboard API.
# ============================================================

st.set_page_config(
    page_title="ESPN NCAA Basketball Schedule Extractor",
    page_icon="🏀",
    layout="wide",
)

st.title("ESPN NCAA Men's & Women's Basketball Schedule Extractor")
st.caption(
    "Extract fixtures from ESPN's schedule-page data and export them to Excel or CSV."
)

SPORTS = {
    "NCAA Men's Basketball": {
        "slug": "mens-college-basketball",
        "page": "https://www.espn.in/mens-college-basketball/schedule",
    },
    "NCAA Women's Basketball": {
        "slug": "womens-college-basketball",
        "page": "https://www.espn.in/womens-college-basketball/schedule",
    },
}

ET = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.espn.in/",
}

OUTPUT_COLUMNS = [
    "Fixture ID",
    "Competition",
    "Start Date (ET)",
    "Start Time (ET)",
    "Start Date (Berlin)",
    "Start Time (Berlin)",
    "Start Date (GMT)",
    "Start Time (GMT)",
    "Home Team",
    "Away Team",
    "Venue",
    "City",
    "Status",
    "ESPN Schedule URL",
    "Game URL",
]


def get_nested(obj, *path, default=""):
    """Safely retrieve a nested dictionary value."""
    value = obj
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def find_event_records(obj):
    """
    Recursively locate game/event records inside ESPN's schedule-page JSON.
    ESPN can change the nesting of its response, so do not assume one fixed
    top-level key.
    """
    found = []
    seen_ids = set()

    def walk(node):
        if isinstance(node, dict):
            event_id = node.get("id") or node.get("gameId") or node.get("eventId")
            event_date = node.get("date") or node.get("startDate")
            event_name = node.get("name") or node.get("shortName")

            competitors = node.get("competitors")
            has_teams = isinstance(competitors, list) and len(competitors) >= 2
            has_matchup_name = isinstance(event_name, str) and (
                " at " in event_name.lower()
                or " vs " in event_name.lower()
                or " vs. " in event_name.lower()
                or " @ " in event_name
            )

            if event_id and event_date and (has_teams or has_matchup_name):
                key = str(event_id)
                if key not in seen_ids:
                    seen_ids.add(key)
                    found.append(node)

            for value in node.values():
                walk(value)

        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


def team_names_from_event(event):
    """Get home and away names from common ESPN event structures."""
    competitions = event.get("competitions") or []
    if competitions and isinstance(competitions[0], dict):
        competitors = competitions[0].get("competitors") or []
        home_name = ""
        away_name = ""

        for team in competitors:
            if not isinstance(team, dict):
                continue
            side = str(team.get("homeAway", "")).lower()
            team_obj = team.get("team", {}) if isinstance(team.get("team"), dict) else {}
            team_name = (
                team_obj.get("displayName")
                or team_obj.get("name")
                or team.get("displayName")
                or team.get("name")
                or ""
            )
            if side == "home":
                home_name = team_name
            elif side == "away":
                away_name = team_name

        if home_name or away_name:
            return home_name, away_name

    # Some schedule-page payloads provide the matchup as event.name.
    name = str(event.get("name") or event.get("shortName") or "")
    lower_name = name.lower()

    for separator in (" at ", " vs. ", " vs ", " @ "):
        index = lower_name.find(separator)
        if index >= 0:
            away = name[:index].strip()
            home = name[index + len(separator):].strip()
            return home, away

    return "", ""


def venue_details(event):
    """Read venue and city from common ESPN event structures."""
    venue = ""
    city = ""

    if isinstance(event.get("venue"), dict):
        venue_obj = event["venue"]
        venue = venue_obj.get("fullName") or venue_obj.get("name") or ""
        address = venue_obj.get("address") or {}
        if isinstance(address, dict):
            city = address.get("city") or ""

    competitions = event.get("competitions") or []
    if competitions and isinstance(competitions[0], dict):
        competition = competitions[0]
        venue_obj = competition.get("venue") or {}
        if isinstance(venue_obj, dict):
            venue = venue or venue_obj.get("fullName") or venue_obj.get("name") or ""
            address = venue_obj.get("address") or {}
            if isinstance(address, dict):
                city = city or address.get("city") or ""

    # Alternate flattened schedule-page fields.
    venue = venue or event.get("venue_full_name") or event.get("venueName") or ""
    city = city or event.get("venue_city") or event.get("city") or ""
    return venue, city


@st.cache_data(ttl=300, show_spinner=False)
def fetch_schedule_date(sport_slug, day_string):
    """
    Fetch one date from ESPN's schedule-page endpoint.
    day_string must be YYYYMMDD.
    """
    url = f"https://cdn.espn.com/core/{sport_slug}/schedule"
    params = {"xhr": "1", "date": day_string}

    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(
            "ESPN returned a non-JSON response for the schedule endpoint."
        ) from exc

    return payload


def parse_schedule_payload(payload, competition_name, sport_slug):
    rows = []
    schedule_page = SPORTS[competition_name]["page"]
    events = find_event_records(payload)

    for event in events:
        event_id = str(
            event.get("id")
            or event.get("gameId")
            or event.get("eventId")
            or ""
        )

        raw_date = event.get("date") or event.get("startDate")
        if not raw_date:
            continue

        timestamp = pd.to_datetime(raw_date, utc=True, errors="coerce")
        if pd.isna(timestamp):
            continue

        home_team, away_team = team_names_from_event(event)
        if not home_team or not away_team:
            continue

        dt_utc = timestamp.to_pydatetime().astimezone(UTC)
        dt_et = dt_utc.astimezone(ET)
        dt_berlin = dt_utc.astimezone(BERLIN)
        venue, city = venue_details(event)

        status = ""
        status_obj = event.get("status") or {}
        if isinstance(status_obj, dict):
            status_type = status_obj.get("type") or {}
            if isinstance(status_type, dict):
                status = (
                    status_type.get("detail")
                    or status_type.get("description")
                    or status_type.get("name")
                    or ""
                )
        status = status or event.get("status_type_detail") or ""

        game_url = ""
        links = event.get("links") or []
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict) and link.get("rel"):
                    rel = link.get("rel")
                    if isinstance(rel, list) and "summary" in rel:
                        game_url = link.get("href", "")
                        break
        if not game_url and event_id:
            game_url = (
                f"https://www.espn.in/{sport_slug}/game/_/gameId/{event_id}"
            )

        rows.append({
            "Fixture ID": event_id,
            "Competition": competition_name,
            "Start Date (ET)": dt_et.strftime("%Y-%m-%d"),
            "Start Time (ET)": dt_et.strftime("%H:%M"),
            "Start Date (Berlin)": dt_berlin.strftime("%Y-%m-%d"),
            "Start Time (Berlin)": dt_berlin.strftime("%H:%M"),
            "Start Date (GMT)": dt_utc.strftime("%Y-%m-%d"),
            "Start Time (GMT)": dt_utc.strftime("%H:%M"),
            "Home Team": home_team,
            "Away Team": away_team,
            "Venue": venue,
            "City": city,
            "Status": status,
            "ESPN Schedule URL": schedule_page,
            "Game URL": game_url,
        })

    return rows, len(events)


def extract_fixtures(start_date, end_date, competition_names, progress_bar, status_text):
    all_rows = []
    errors = []
    total_days = (end_date - start_date).days + 1
    total_requests = total_days * len(competition_names)
    request_number = 0

    current_date = start_date
    while current_date <= end_date:
        # The schedule endpoint is keyed to US Eastern dates.
        date_key = current_date.strftime("%Y%m%d")

        for competition_name in competition_names:
            request_number += 1
            sport_slug = SPORTS[competition_name]["slug"]
            status_text.text(
                f"Fetching {competition_name}: {current_date:%d %b %Y} "
                f"({request_number}/{total_requests})"
            )

            try:
                payload = fetch_schedule_date(sport_slug, date_key)
                rows, _ = parse_schedule_payload(
                    payload, competition_name, sport_slug
                )
                all_rows.extend(rows)
            except Exception as exc:
                errors.append({
                    "Date": current_date.isoformat(),
                    "Competition": competition_name,
                    "Error": str(exc),
                })

            progress_bar.progress(min(request_number / total_requests, 1.0))
            # Small delay to reduce the chance of ESPN rate limiting requests.
            time.sleep(0.15)

        current_date += timedelta(days=1)

    if not all_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), errors

    df = pd.DataFrame(all_rows)

    # Keep fixtures whose US Eastern start date falls within the selected range.
    df = df[
        (df["Start Date (ET)"] >= start_date.isoformat())
        & (df["Start Date (ET)"] <= end_date.isoformat())
    ]

    df = df.drop_duplicates(subset=["Fixture ID"], keep="first")
    df = df.reindex(columns=OUTPUT_COLUMNS)
    df = df.sort_values(
        ["Start Date (ET)", "Start Time (ET)", "Competition", "Home Team"],
        na_position="last",
    ).reset_index(drop=True)

    return df, errors


def to_excel_bytes(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="NCAA Fixtures")
    output.seek(0)
    return output.getvalue()


with st.sidebar:
    st.header("Extraction settings")
    selected_competitions = st.multiselect(
        "Select schedule page",
        options=list(SPORTS.keys()),
        default=list(SPORTS.keys()),
    )
    start_date = st.date_input(
        "Start date",
        value=date(2026, 11, 1),
    )
    end_date = st.date_input(
        "End date",
        value=date(2027, 4, 15),
    )

st.markdown(
    "**Source:** ESPN schedule-page data endpoint (`cdn.espn.com/core/.../schedule`). "
    "The app does not use the scoreboard endpoint."
)

st.info(
    "The schedule endpoint is date-based for NCAA basketball. "
    "A full season can take several minutes because the app requests each date "
    "for each selected competition. ESPN can only return fixtures it has published."
)

if start_date > end_date:
    st.error("Start date must be on or before end date.")
elif not selected_competitions:
    st.warning("Select at least one schedule page.")
elif (end_date - start_date).days > 365:
    st.error("Please select a date range of 365 days or less.")
else:
    if st.button("Extract Schedule Fixtures", type="primary"):
        progress = st.progress(0)
        status = st.empty()

        with st.spinner("Extracting ESPN schedule-page fixtures..."):
            fixtures_df, errors = extract_fixtures(
                start_date,
                end_date,
                selected_competitions,
                progress,
                status,
            )

        status.empty()

        if not fixtures_df.empty:
            st.success(f"Extracted {len(fixtures_df):,} schedule fixtures.")
            st.dataframe(fixtures_df, use_container_width=True, hide_index=True)

            csv_bytes = fixtures_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Download CSV",
                data=csv_bytes,
                file_name="NCAA_Basketball_Schedule_Fixtures.csv",
                mime="text/csv",
            )
            st.download_button(
                "Download Excel",
                data=to_excel_bytes(fixtures_df),
                file_name="NCAA_Basketball_Schedule_Fixtures.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.warning(
                "No fixtures were parsed from the schedule-page response. "
                "This may mean ESPN changed its JSON structure or has not "
                "published fixtures for the selected dates."
            )

        if errors:
            with st.expander(f"View {len(errors)} request error(s)"):
                st.dataframe(pd.DataFrame(errors), use_container_width=True)

        if not fixtures_df.empty and not errors:
            st.caption("All date requests completed without reported errors.")
