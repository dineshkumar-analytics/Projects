
import streamlit as st
import pandas as pd
from difflib import SequenceMatcher
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from io import BytesIO

# ================= PAGE CONFIG =================
st.set_page_config(
    page_title="Fixture Comparison Tool",
    layout="wide"
)

st.title("Fixture Comparison Tool")
st.caption(
    "Detect added, removed, and modified fixtures, "
    "including spelling differences."
)

# ================= CONFIGURATION =================
MATCH_THRESHOLD = 0.90

REQUIRED_COLS = [
    "Start Date",
    "Start Time",
    "Description",
    "Venue"
]

# ================= NORMALIZATION =================
def normalize_desc(text):
    if pd.isna(text):
        return ""

    return " ".join(str(text).lower().split())


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def clean_columns(df):
    """Standardize headers to avoid KeyError."""
    df = df.copy()

    # Remove extra spaces and normalize case
    df.columns = [
        " ".join(str(col).strip().split()).lower()
        for col in df.columns
    ]

    # Map common header variations to standard names
    aliases = {
        "start date": "Start Date",
        "date": "Start Date",
        "start time": "Start Time",
        "time": "Start Time",
        "description": "Description",
        "fixture": "Description",
        "fixture description": "Description",
        "match": "Description",
        "venue": "Venue",
        "stadium": "Venue"
    }

    rename_map = {
        col: aliases[col]
        for col in df.columns
        if col in aliases
    }

    df = df.rename(columns=rename_map)

    return df


def load_fixture_file(uploaded_file):
    """Read and validate an uploaded Excel file."""
    df = pd.read_excel(uploaded_file)
    df = clean_columns(df)

    missing_cols = [
        col for col in REQUIRED_COLS
        if col not in df.columns
    ]

    if missing_cols:
        raise ValueError(
            f"Missing required columns: {missing_cols}. "
            f"Available columns: {df.columns.tolist()}"
        )

    # Select only the required columns
    df = df[REQUIRED_COLS].copy()

    # Standardize text values
    for col in ["Description", "Venue"]:
        df[col] = df[col].map(
            lambda x: x.strip() if isinstance(x, str) else x
        )

    # Reset index for reliable row matching
    df = df.reset_index(drop=True)

    # Normalize descriptions for fuzzy matching
    df["Desc_norm"] = df["Description"].apply(normalize_desc)

    return df


# ================= STREAMLIT HIGHLIGHT =================
def highlight_row(row):
    change_type = str(row["Change Type"])

    if change_type == "ADDED":
        color = "background-color: #C6EFCE"
    elif change_type == "REMOVED":
        color = "background-color: #FFC7CE"
    elif change_type.startswith("MODIFIED"):
        color = "background-color: #FFEB9C"
    else:
        color = ""

    return [color] * len(row)


# ================= COMPARISON LOGIC =================
def compare_fixtures(old_df, new_df):
    matched_new = set()
    pairs = []

    # Match each OLD fixture with the closest NEW description
    for old_i, old_row in old_df.iterrows():
        best_match = None
        best_score = 0

        for new_j, new_row in new_df.iterrows():
            if new_j in matched_new:
                continue

            # Empty descriptions should not fuzzy-match
            if not old_row["Desc_norm"] or not new_row["Desc_norm"]:
                continue

            score = similarity(
                old_row["Desc_norm"],
                new_row["Desc_norm"]
            )

            if score > best_score:
                best_score = score
                best_match = new_j

        if best_match is not None and best_score >= MATCH_THRESHOLD:
            matched_new.add(best_match)
            pairs.append((old_i, best_match))
        else:
            pairs.append((old_i, None))

    # Add NEW fixtures that did not match an OLD fixture
    for new_j in new_df.index:
        if new_j not in matched_new:
            pairs.append((None, new_j))

    # Build results
    rows = []

    for old_i, new_i in pairs:
        old = old_df.loc[old_i] if old_i is not None else None
        new = new_df.loc[new_i] if new_i is not None else None

        if old is None:
            change_type = "ADDED"

        elif new is None:
            change_type = "REMOVED"

        else:
            changes = []

            # Compare values safely, including blank cells
            for col in REQUIRED_COLS:
                old_val = old[col]
                new_val = new[col]

                if pd.isna(old_val) and pd.isna(new_val):
                    continue

                if pd.isna(old_val) or pd.isna(new_val):
                    changes.append(col)
                    continue

                # Compare dates and times consistently
                if col == "Start Date":
                    old_compare = pd.to_datetime(
                        old_val, errors="coerce"
                    )
                    new_compare = pd.to_datetime(
                        new_val, errors="coerce"
                    )

                    if pd.isna(old_compare) or pd.isna(new_compare):
                        changed = str(old_val).strip() != str(new_val).strip()
                    else:
                        changed = old_compare.normalize() != new_compare.normalize()

                elif col == "Start Time":
                    old_compare = str(old_val).strip()
                    new_compare = str(new_val).strip()
                    changed = old_compare != new_compare

                else:
                    old_compare = normalize_desc(old_val)
                    new_compare = normalize_desc(new_val)
                    changed = old_compare != new_compare

                if changed:
                    changes.append(col)

            if changes:
                change_type = "MODIFIED (" + ", ".join(changes) + ")"
            else:
                change_type = "NO CHANGE"

        rows.append({
            "Change Type": change_type,
            "Description_OLD": old["Description"] if old is not None else "",
            "Description_NEW": new["Description"] if new is not None else "",
            "Start Date_OLD": old["Start Date"] if old is not None else "",
            "Start Time_OLD": old["Start Time"] if old is not None else "",
            "Venue_OLD": old["Venue"] if old is not None else "",
            "Start Date_NEW": new["Start Date"] if new is not None else "",
            "Start Time_NEW": new["Start Time"] if new is not None else "",
            "Venue_NEW": new["Venue"] if new is not None else "",
        })

    return pd.DataFrame(rows)


# ================= FILE UPLOAD =================
col1, col2 = st.columns(2)

with col1:
    old_file = st.file_uploader(
        "Upload OLD Fixture File",
        type=["xlsx", "xls"],
        key="old_upload"
    )

with col2:
    new_file = st.file_uploader(
        "Upload NEW Fixture File",
        type=["xlsx", "xls"],
        key="new_upload"
    )


# ================= PROCESS FILES =================
if old_file is not None and new_file is not None:

    try:
        old_df = load_fixture_file(old_file)
        new_df = load_fixture_file(new_file)

        st.success("Both files uploaded and validated successfully!")

        with st.expander("View input column names"):
            st.write("Required columns:", REQUIRED_COLS)
            st.write("Old file:", old_df.columns.tolist())
            st.write("New file:", new_df.columns.tolist())

        preview1, preview2 = st.columns(2)

        with preview1:
            st.subheader("Old File Preview")
            st.dataframe(
                old_df[REQUIRED_COLS].head(10),
                use_container_width=True
            )

        with preview2:
            st.subheader("New File Preview")
            st.dataframe(
                new_df[REQUIRED_COLS].head(10),
                use_container_width=True
            )

        if st.button("Compare Fixtures", type="primary"):

            final_df = compare_fixtures(old_df, new_df)

            st.session_state["fixture_comparison"] = final_df

        if "fixture_comparison" in st.session_state:

            final_df = st.session_state["fixture_comparison"]

            st.subheader("Comparison Summary")

            metric1, metric2, metric3, metric4 = st.columns(4)

            metric1.metric(
                "Added",
                int((final_df["Change Type"] == "ADDED").sum())
            )

            metric2.metric(
                "Removed",
                int((final_df["Change Type"] == "REMOVED").sum())
            )

            metric3.metric(
                "Modified",
                int(
                    final_df["Change Type"]
                    .astype(str)
                    .str.startswith("MODIFIED")
                    .sum()
                )
            )

            metric4.metric(
                "No Change",
                int((final_df["Change Type"] == "NO CHANGE").sum())
            )

            # ================= PREVIEW =================
            st.subheader("Comparison Preview")

            filter_option = st.selectbox(
                "Filter results",
                [
                    "All",
                    "ADDED",
                    "REMOVED",
                    "MODIFIED",
                    "NO CHANGE"
                ]
            )

            if filter_option == "All":
                display_df = final_df
            elif filter_option == "MODIFIED":
                display_df = final_df[
                    final_df["Change Type"]
                    .astype(str)
                    .str.startswith("MODIFIED")
                ]
            else:
                display_df = final_df[
                    final_df["Change Type"] == filter_option
                ]

            st.dataframe(
                display_df.style.apply(highlight_row, axis=1),
                use_container_width=True
            )

            # ================= EXCEL EXPORT =================
            output = BytesIO()

            with pd.ExcelWriter(
                output,
                engine="openpyxl"
            ) as writer:
                final_df.to_excel(
                    writer,
                    index=False,
                    sheet_name="Comparison"
                )

            output.seek(0)

            # Apply row highlights in Excel
            wb = load_workbook(output)
            ws = wb["Comparison"]

            fill_added = PatternFill(
                "solid", fgColor="C6EFCE"
            )
            fill_removed = PatternFill(
                "solid", fgColor="FFC7CE"
            )
            fill_modified = PatternFill(
                "solid", fgColor="FFEB9C"
            )

            headers = [
                cell.value for cell in ws[1]
            ]
            change_col_idx = headers.index("Change Type") + 1

            for row_num in range(2, ws.max_row + 1):
                value = str(
                    ws.cell(row_num, change_col_idx).value
                )

                if value == "ADDED":
                    fill = fill_added
                elif value == "REMOVED":
                    fill = fill_removed
                elif value.startswith("MODIFIED"):
                    fill = fill_modified
                else:
                    continue

                for col_num in range(1, ws.max_column + 1):
                    ws.cell(row_num, col_num).fill = fill

            # Prepare the final workbook in memory
            final_output = BytesIO()
            wb.save(final_output)
            final_output.seek(0)

            st.download_button(
                label="Download Highlighted Comparison Report",
                data=final_output.getvalue(),
                file_name="Fixture_Comparison_Report.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                )
            )

    except Exception as e:
        st.error(f"Unable to process the files: {e}")
        st.info(
            "Check the required column names and the Excel file format. "
            "The error message above identifies the issue."
        )

else:
    st.info(
        "Please upload both OLD and NEW Excel files to start comparison."
    )
