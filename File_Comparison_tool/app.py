
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date, datetime, time
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment

# ==================================================
# 1. PAGE CONFIGURATION
# ==================================================
st.set_page_config(
    page_title="Basketball Fixture Comparison Tool",
    page_icon="🏀",
    layout="wide"
)

st.title("🏀 Basketball Fixture Comparison Tool")
st.caption(
    "Compare OLD and NEW fixture files using Fixture ID. "
    "Detect added, removed, and modified fixtures."
)

# ==================================================
# 2. CONFIGURATION
# ==================================================
KEY_COLUMN = "Fixture ID"

# These columns will be checked first.
# All other matching columns in both files will also be compared.
PRIORITY_COLUMNS = [
    "Date & Time (Berlin)",
    "Start Date",
    "Start Time",
    "Description",
    "Venue",
    "GSM Basketball",
    "STATS Basketball",
    "User Modified Time",
    "Sport",
    "Sport Id",
    "Ruleset",
    "Ruleset Id",
    "Country",
    "Country Id",
    "Competition",
    "Competition Id",
    "Tournament Calendar",
    "Tournament Calendar Id",
    "Stage",
    "Stage Id",
    "Series",
    "Series Id",
    "Venue Id",
    "Contestant 1",
    "Contestant 1 Id",
    "Contestant 2",
    "Contestant 2 Id"
]

# ==================================================
# 3. NORMALIZE EXCEL COLUMN NAMES
# ==================================================
def clean_columns(df):
    """
    Remove extra spaces and safely handle duplicate headers.
    Pandas may read duplicate headers as Description.1, Venue.1.
    """

    df = df.copy()
    cleaned = []
    seen = {}

    for original in df.columns:
        name = " ".join(str(original).strip().split())

        # Handle headers already suffixed by pandas
        # when the original Excel file has duplicate names.
        import re

        match = re.match(r"^(.*)\.(\d+)$", name)

        if match and match.group(1).strip().lower() in {
            "description", "venue"
        }:
            base = match.group(1).strip()
            number = int(match.group(2)) + 1
            name = f"{base} ({number})"

        count = seen.get(name.lower(), 0) + 1
        seen[name.lower()] = count

        if count > 1:
            name = f"{name} ({count})"

        cleaned.append(name)

    df.columns = cleaned

    # Standardize common variations of the fixture ID
    aliases = {
        "fixture id": "Fixture ID",
        "fixtureid": "Fixture ID",
        "fixture_id": "Fixture ID",
        "match id": "Fixture ID",
        "matchid": "Fixture ID"
    }

    rename_map = {}

    for col in df.columns:
        if col.strip().lower() in aliases:
            rename_map[col] = aliases[col.strip().lower()]

    df = df.rename(columns=rename_map)

    # Remove completely empty Excel columns
    df = df.loc[
        :,
        [
            col for col in df.columns
            if not col.lower().startswith("unnamed:")
        ]
    ]

    return df


# ==================================================
# 4. READ AND VALIDATE EXCEL FILES
# ==================================================
def read_fixture_file(uploaded_file):
    df = pd.read_excel(uploaded_file, dtype=object)
    df = clean_columns(df)

    if KEY_COLUMN not in df.columns:
        raise ValueError(
            f"'{KEY_COLUMN}' column was not found. "
            f"Available columns: {df.columns.tolist()}"
        )

    # Clean whitespace in text values
    for col in df.columns:
        df[col] = df[col].map(
            lambda x: x.strip()
            if isinstance(x, str)
            else x
        )

    # Remove rows without a fixture ID
    missing_ids = df[KEY_COLUMN].isna() | (
        df[KEY_COLUMN].astype(str).str.strip() == ""
    )

    if missing_ids.any():
        raise ValueError(
            f"{int(missing_ids.sum())} row(s) have no Fixture ID. "
            "Please correct these rows in Excel."
        )

    # Use consistent string IDs for matching
    df[KEY_COLUMN] = df[KEY_COLUMN].astype(str).str.strip()

    # Detect duplicate IDs
    duplicates = df.loc[
        df[KEY_COLUMN].duplicated(keep=False),
        KEY_COLUMN
    ].unique()

    if len(duplicates) > 0:
        raise ValueError(
            "Duplicate Fixture ID values were found: "
            + ", ".join(map(str, duplicates[:10]))
            + ". Each fixture must have a unique ID."
        )

    return df


# ==================================================
# 5. VALUE COMPARISON
# ==================================================
def canonical_value(value):
    """
    Standardize values so Excel dates and equivalent values
    can be compared reliably.
    """

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, time):
        return value.isoformat()

    if isinstance(value, str):
        return " ".join(value.split())

    # Treat Excel 10 and 10.0 as equal
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            return int(value)

    return value


def values_equal(old_value, new_value):
    old_value = canonical_value(old_value)
    new_value = canonical_value(new_value)

    if old_value is None and new_value is None:
        return True

    if old_value is None or new_value is None:
        return False

    return old_value == new_value


# ==================================================
# 6. FIXTURE COMPARISON
# ==================================================
def compare_fixtures(old_df, new_df):

    old_ids = set(old_df[KEY_COLUMN])
    new_ids = set(new_df[KEY_COLUMN])

    added_ids = new_ids - old_ids
    removed_ids = old_ids - new_ids
    common_ids = old_ids & new_ids

    # Compare fields shared by both files
    shared_columns = [
        col for col in old_df.columns
        if col in new_df.columns and col != KEY_COLUMN
    ]

    # Compare priority fields first, then other shared fields
    ordered_columns = [
        col for col in PRIORITY_COLUMNS
        if col in shared_columns
    ]

    ordered_columns += [
        col for col in shared_columns
        if col not in ordered_columns
    ]

    results = []
    details = []

    old_lookup = old_df.set_index(KEY_COLUMN, drop=False)
    new_lookup = new_df.set_index(KEY_COLUMN, drop=False)

    # ---------------- ADDED FIXTURES ----------------
    for fixture_id in sorted(added_ids):
        new_row = new_lookup.loc[fixture_id]

        record = {
            "Change Type": "ADDED",
            KEY_COLUMN: fixture_id
        }

        for col in ordered_columns:
            record[f"{col} (OLD)"] = None
            record[f"{col} (NEW)"] = new_row[col]

        results.append(record)

    # ---------------- REMOVED FIXTURES ----------------
    for fixture_id in sorted(removed_ids):
        old_row = old_lookup.loc[fixture_id]

        record = {
            "Change Type": "REMOVED",
            KEY_COLUMN: fixture_id
        }

        for col in ordered_columns:
            record[f"{col} (OLD)"] = old_row[col]
            record[f"{col} (NEW)"] = None

        results.append(record)

    # ---------------- EXISTING FIXTURES ----------------
    for fixture_id in sorted(common_ids):
        old_row = old_lookup.loc[fixture_id]
        new_row = new_lookup.loc[fixture_id]

        changed_columns = []

        for col in ordered_columns:
            old_value = old_row[col]
            new_value = new_row[col]

            if not values_equal(old_value, new_value):
                changed_columns.append(col)

                details.append({
                    KEY_COLUMN: fixture_id,
                    "Changed Column": col,
                    "Old Value": old_value,
                    "New Value": new_value
                })

        change_type = (
            "MODIFIED (" + ", ".join(changed_columns) + ")"
            if changed_columns
            else "NO CHANGE"
        )

        record = {
            "Change Type": change_type,
            KEY_COLUMN: fixture_id
        }

        for col in ordered_columns:
            record[f"{col} (OLD)"] = old_row[col]
            record[f"{col} (NEW)"] = new_row[col]

        results.append(record)

    result_df = pd.DataFrame(results)

    detail_columns = [
        KEY_COLUMN,
        "Changed Column",
        "Old Value",
        "New Value"
    ]

    detail_df = pd.DataFrame(
        details,
        columns=detail_columns
    )

    return result_df, detail_df, ordered_columns


# ==================================================
# 7. HIGHLIGHT COMPARISON ROWS
# ==================================================
def highlight_row(row):
    change_type = str(row.get("Change Type", ""))

    if change_type == "ADDED":
        color = "#C6EFCE"
    elif change_type == "REMOVED":
        color = "#FFC7CE"
    elif change_type.startswith("MODIFIED"):
        color = "#FFEB9C"
    else:
        color = ""

    return [
        f"background-color: {color}" if color else ""
        for _ in row
    ]


# ==================================================
# 8. FILE UPLOAD
# ==================================================
col1, col2 = st.columns(2)

with col1:
    old_file = st.file_uploader(
        "Upload OLD Fixture File",
        type=["xlsx", "xls"],
        key="old_file"
    )

with col2:
    new_file = st.file_uploader(
        "Upload NEW Fixture File",
        type=["xlsx", "xls"],
        key="new_file"
    )


# ==================================================
# 9. PROCESS FILES
# ==================================================
if old_file is not None and new_file is not None:

    try:
        old_df = read_fixture_file(old_file)
        new_df = read_fixture_file(new_file)

        st.success("Both fixture files loaded successfully.")

        # Preview
        with st.expander("View column names and file previews"):
            preview1, preview2 = st.columns(2)

            with preview1:
                st.write("OLD file columns")
                st.write(old_df.columns.tolist())
                st.dataframe(old_df.head(5), use_container_width=True)

            with preview2:
                st.write("NEW file columns")
                st.write(new_df.columns.tolist())
                st.dataframe(new_df.head(5), use_container_width=True)

        if st.button("Compare Fixtures", type="primary"):

            result_df, detail_df, compared_columns = compare_fixtures(
                old_df,
                new_df
            )

            st.session_state["fixture_result"] = result_df
            st.session_state["fixture_details"] = detail_df
            st.session_state["compared_columns"] = compared_columns

        if "fixture_result" in st.session_state:

            result_df = st.session_state["fixture_result"]
            detail_df = st.session_state["fixture_details"]
            compared_columns = st.session_state["compared_columns"]

            # ---------------- SUMMARY ----------------
            added_count = int(
                (result_df["Change Type"] == "ADDED").sum()
            )
            removed_count = int(
                (result_df["Change Type"] == "REMOVED").sum()
            )
            modified_count = int(
                result_df["Change Type"]
                .astype(str)
                .str.startswith("MODIFIED")
                .sum()
            )
            unchanged_count = int(
                (result_df["Change Type"] == "NO CHANGE").sum()
            )

            st.subheader("Comparison Summary")

            m1, m2, m3, m4 = st.columns(4)

            m1.metric("Added Fixtures", added_count)
            m2.metric("Removed Fixtures", removed_count)
            m3.metric("Modified Fixtures", modified_count)
            m4.metric("No Change", unchanged_count)

            # ---------------- FILTER ----------------
            st.subheader("Comparison Results")

            filter_option = st.selectbox(
                "Filter by change type",
                [
                    "All",
                    "ADDED",
                    "REMOVED",
                    "MODIFIED",
                    "NO CHANGE"
                ]
            )

            if filter_option == "All":
                filtered_df = result_df
            elif filter_option == "MODIFIED":
                filtered_df = result_df[
                    result_df["Change Type"]
                    .astype(str)
                    .str.startswith("MODIFIED")
                ]
            else:
                filtered_df = result_df[
                    result_df["Change Type"] == filter_option
                ]

            st.dataframe(
                filtered_df.style.apply(highlight_row, axis=1),
                use_container_width=True
            )

            st.subheader("Individual Field Changes")
            st.dataframe(detail_df, use_container_width=True)

            st.caption(
                "Compared columns: "
                + ", ".join(compared_columns)
            )

            # ---------------- EXCEL REPORT ----------------
            output = BytesIO()

            with pd.ExcelWriter(
                output,
                engine="openpyxl"
            ) as writer:

                result_df.to_excel(
                    writer,
                    index=False,
                    sheet_name="Comparison"
                )

                detail_df.to_excel(
                    writer,
                    index=False,
                    sheet_name="Change Details"
                )

                old_df.to_excel(
                    writer,
                    index=False,
                    sheet_name="Old File"
                )

                new_df.to_excel(
                    writer,
                    index=False,
                    sheet_name="New File"
                )

            output.seek(0)

            workbook = load_workbook(output)

            fill_added = PatternFill(
                "solid", fgColor="C6EFCE"
            )
            fill_removed = PatternFill(
                "solid", fgColor="FFC7CE"
            )
            fill_modified = PatternFill(
                "solid", fgColor="FFEB9C"
            )

            # Highlight comparison rows
            ws = workbook["Comparison"]
            headers = [
                cell.value for cell in ws[1]
            ]
            change_col = headers.index("Change Type") + 1

            for row_num in range(2, ws.max_row + 1):
                value = str(
                    ws.cell(row_num, change_col).value
                )

                if value == "ADDED":
                    fill = fill_added
                elif value == "REMOVED":
                    fill = fill_removed
                elif value.startswith("MODIFIED"):
                    fill = fill_modified
                else:
                    continue

                for cell in ws[row_num]:
                    cell.fill = fill

            # Highlight field changes
            ws_details = workbook["Change Details"]

            for row_num in range(2, ws_details.max_row + 1):
                for cell in ws_details[row_num]:
                    cell.fill = fill_modified

            # Format report sheets
            for sheet in workbook.worksheets:
                sheet.freeze_panes = "A2"
                sheet.auto_filter.ref = sheet.dimensions

                for cell in sheet[1]:
                    cell.font = Font(bold=True)
                    cell.alignment = Alignment(
                        vertical="top",
                        wrap_text=True
                    )

                for column_cells in sheet.columns:
                    letter = column_cells[0].column_letter
                    max_length = 0

                    for cell in column_cells[:100]:
                        value = (
                            "" if cell.value is None
                            else str(cell.value)
                        )
                        max_length = max(max_length, len(value))

                    sheet.column_dimensions[letter].width = min(
                        max(max_length + 2, 12),
                        35
                    )

            final_output = BytesIO()
            workbook.save(final_output)
            final_output.seek(0)

            st.download_button(
                label="Download Highlighted Comparison Report",
                data=final_output.getvalue(),
                file_name="Basketball_Fixture_Comparison.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                )
            )

    except Exception as error:
        st.error(f"Unable to compare files: {error}")

else:
    st.info(
        "Upload both OLD and NEW Excel files to start comparison."
    )
