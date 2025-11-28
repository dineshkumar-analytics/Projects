import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
from io import BytesIO

# ==============================
# CONFIG: ESPN API COMPETITIONS
# ==============================
COMPETITIONS = {
    "Men's NCAA Basketball": "basketball/mens-college-basketball",
    "Women's NCAA Basketball": "basketball/womens-college-basketball"
}

CONFERENCES = {
    "ACC": 2, "Big Ten": 7, "SEC": 8, "Big 12": 4, "Pac-12": 21, "Big East": 3, 
    "AAC": 62, "Mountain West": 46, "Atlantic 10": 3, "WCC": 26, "Sun Belt": 27,
    "MAAC": 5, "Horizon": 24, "Ivy League": 12, "Patriot League": 31, "America East": 1,
    "MEAC": 16, "SWAC": 23, "ASUN": 55, "Missouri Valley": 9, "CAA": 10,
    "Ohio Valley": 14, "Summit League": 44
}


# ===========================
# FETCH FIXTURES FUNCTION
# ===========================

def fetch_fixtures(start_date, end_date, gender_url):
    base_url = f"https://site.api.espn.com/apis/site/v2/sports/{gender_url}/scoreboard"
    all_games = []

    date_cursor = start_date
    while date_cursor <= end_date:
        date_str = date_cursor.strftime("%Y%m%d")
        
        for conference_name, group_id in CONFERENCES.items():
            url = f"{base_url}?dates={date_str}&groups={group_id}"
            resp = requests.get(url)

            if resp.status_code != 200:
                continue

            data = resp.json()

            for event in data.get("events", []):
                game = event["competitions"][0]

                teams = game["competitors"]
                status = game["status"]["type"]["description"]
                ko_time = event.get("date", None)

                # Convert KO Time
                if ko_time:
                    ko_time = datetime.fromisoformat(ko_time.replace('Z', '')).strftime("%I:%M %p")

                all_games.append({
                    "Date": date_cursor.strftime("%d-%m-%Y"),
                    "KO Time": ko_time,
                    "Competition": gender_url.split("/")[1],
                    "Conference": conference_name,
                    "Home Team": teams[0]["team"]["displayName"].upper(),
                    "Away Team": teams[1]["team"]["displayName"].upper(),
                    "Home Score": teams[0].get("score", None),
                    "Away Score": teams[1].get("score", None),
                    "Status": status
                })

        date_cursor += timedelta(days=1)

    df = pd.DataFrame(all_games)

    # Create Unique Key
    df["Game_Key"] = df["Date"] + "_" + df["Home Team"] + "_" + df["Away Team"]

    # Duplicate Flagging
    df["Is_Duplicate"] = df.duplicated(subset=["Game_Key"], keep=False)

    return df


# ===========================
# STREAMLIT UI
# ===========================

st.title("🏀 NCAA Full Season Fixture Extractor")

competition = st.selectbox("Select Competition:", list(COMPETITIONS.keys()))

col1, col2 = st.columns(2)
start_date = col1.date_input("Start Date", datetime.today())
end_date = col2.date_input("End Date", datetime.today())

if st.button("🔍 Fetch Fixtures"):
    st.info("Fetching data... Please wait.")

    gender_url = COMPETITIONS[competition]
    df = fetch_fixtures(datetime.combine(start_date, datetime.min.time()),
                        datetime.combine(end_date, datetime.min.time()),
                        gender_url)

    st.success(f"✔ Data Loaded — {len(df)} rows extracted")

    st.dataframe(df.head(50))

    # Duplicate subset
    dup_df = df[df["Is_Duplicate"] == True]

    # Create Excel with formatting
    output = BytesIO()
    
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Full Fixtures", index=False)
        dup_df.to_excel(writer, sheet_name="Duplicate Fixtures", index=False)

        workbook = writer.book
        worksheet = writer.sheets["Full Fixtures"]

        highlight = workbook.add_format({"bg_color": "#FFDDDD", "font_color": "black"})

        for row_idx, is_dup in enumerate(df["Is_Duplicate"], start=1):
            if is_dup:
                worksheet.set_row(row_idx, cell_format=highlight)

    st.download_button(
        label="📥 Download Excel File",
        data=output.getvalue(),
        file_name=f"NCAA_Fixtures_{competition.replace(' ', '_')}_{start_date}_to_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
