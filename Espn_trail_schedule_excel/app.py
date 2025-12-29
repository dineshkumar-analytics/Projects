import streamlit as st
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import time

st.set_page_config(page_title="Team Comparison Tool", layout="wide")
st.title("Compare TEAM A & TEAM B Between Two Excel Files")

# Upload old and new files
old_file = st.file_uploader("Upload OLD Excel file", type=["xlsx"])
new_file = st.file_uploader("Upload NEW Excel file", type=["xlsx"])

if old_file and new_file:
    # Load ONLY first two columns, ignore headers
    old_df = pd.read_excel(old_file, usecols=[0, 1], header=None)
    new_df = pd.read_excel(new_file, usecols=[0, 1], header=None)

    # Rename columns
    old_df.columns = ["TEAM A_OLD", "TEAM B_OLD"]
    new_df.columns = ["TEAM A_NEW", "TEAM B_NEW"]

    # Align lengths
    max_len = max(len(old_df), len(new_df))
    old_df = old_df.reindex(range(max_len))
    new_df = new_df.reindex(range(max_len))

    # Combine
    combined = pd.concat([old_df, new_df], axis=1)

    # Create a mask of differences (ignore extra spaces)
    diff_mask = pd.DataFrame(False, index=combined.index, columns=combined.columns)
    for old_col, new_col in [("TEAM A_OLD", "TEAM A_NEW"), ("TEAM B_OLD", "TEAM B_NEW")]:
        diff = combined[old_col].astype(str).str.strip() != combined[new_col].astype(str).str.strip()
        diff_mask[old_col] = diff
        diff_mask[new_col] = diff

    # Display in Streamlit with highlight
    def highlight_diff(row):
        return ['background-color: yellow' if diff_mask.iloc[row.name, i] else '' for i in range(len(row))]

    st.write("### Comparison Result")
    st.dataframe(combined.style.apply(highlight_diff, axis=1), use_container_width=True)

    # Generate a unique filename to avoid PermissionError
    OUTPUT = f"teams_difference_highlight_{int(time.time())}.xlsx"

    # Save Excel without headers
    combined.to_excel(OUTPUT, index=False, header=False)

    # Apply yellow highlights in Excel
    wb = load_workbook(OUTPUT)
    ws = wb.active
    yellow = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

    for row_idx in range(1, max_len + 1):
        for col_idx, col_name in enumerate(combined.columns, start=1):
            if diff_mask.iloc[row_idx - 1, col_idx - 1]:
                ws.cell(row=row_idx, column=col_idx).fill = yellow

    wb.save(OUTPUT)

    st.success(f"✅ Comparison complete! Differences highlighted in Excel: `{OUTPUT}`")
    with open(OUTPUT, "rb") as f:
        st.download_button("Download Highlighted Excel", f, file_name=OUTPUT)

else:
    st.info("Please upload both OLD and NEW Excel files to compare.")
