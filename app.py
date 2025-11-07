from __future__ import annotations

from pathlib import Path
from typing import List
import pandas as pd
import streamlit as st

# ---------- Utilities (moved to functions.py) ----------
from functions.functions import (
    coerce_named_date_columns,
    export_xlsx_bytes,
    extract_dates_from_filename,
)

# ---------- Config ----------
# BASE = Path("/Users/andyburnett/Library/Mobile Documents/com~apple~CloudDocs/Desktop/X03.27.25/OVS/Special Projects/em_report_project/v5")
BASE = Path("exports")

# ---------- App ----------
st.set_page_config(page_title="EM Reports", layout="wide")
st.title("EM Report Compiler")
st.divider()
st.subheader("Detailed Reports")

st.sidebar.header("Report Period")
period = st.sidebar.date_input(
    "From and To (inclusive)",
    value=(pd.Timestamp.today().date(), pd.Timestamp.today().date()),
)
if isinstance(period, tuple):
    date_from, date_to = period
else:
    date_from = date_to = period

st.subheader("1 | Upload up to 100 CSV reports")
files = st.file_uploader(
    "CSV files",
    type=["csv"],
    accept_multiple_files=True,
    help="Drop up to 100 CSVs or less."
)
files = files[:100] if files else []

# --- SCO mapping (defined once) ---
SCO_MAP_RAW = {
    "CRUZ; ASHLIE": "Ashlie",
    "FITZGERALD; ZACHARY": "Zach",
    "GRABARZ; FRANK": "Frank",
    "JACKS; MELISSSA": "Melissa",
    "MCAFEE; CLIFFORD": "Clif",
    "POST; TODD": "Todd",
    "RAINS; SAVANNA": "Savanna",
    "WOJTIUK; BRADLEY": "Brad",
    "MOULDEN; MATTHEW": "Matthew",
    "VANDA; JESSICA": "Jessica",
    "EMOND; ELIJAH": "Elijah",
    "BUTTERFIELD; KATHERINE": "Katherine",
    "COSS; SAVANNA": "Savanna",
    "MONTROS; DENNIS": "Dennis",
    "AGNEW; JACQUELINE": "Jackie",  # correct spelling
    "AGNEW; JAQUELINE": "Jackie",    # alias for common misspelling
}

def _norm_key(s: str) -> str:
    return str(s).strip().upper().replace('\u00A0', ' ')

SCO_MAP = {_norm_key(k): v for k, v in SCO_MAP_RAW.items()}

st.subheader("2 | Build unified table and export")
if st.button("Build & Export XLSX", use_container_width=True, disabled=not files):
    frames: List[pd.DataFrame] = []

    for f in files:
        df = pd.read_csv(f)

        # 1) Extract dates from the filename (MM.DD.YY_MM.DD.YY or MM-DD-YYYY_MM-DD-YYYY)
        f_from, f_to = extract_dates_from_filename(f.name)

        # 2) Fall back to sidebar period if filename dates are missing
        from_dt = pd.to_datetime(f_from or date_from)
        to_dt   = pd.to_datetime(f_to   or date_to)

        # Insert non-EM columns ----
        # Year
        year_val = from_dt.year        # e.g., 2025 (int)
        month_val = from_dt

        # Insert new columns in correct order
        # 1) Year (first column)
        df.insert(0, "Year", year_val)
        # 2) Month (second column)
        df.insert(1, "Month", month_val)
        # 3) From (third column)
        df.insert(2, "From", from_dt)
        # 4) To (fourth column)
        df.insert(3, "To", to_dt)
        
        # 5) SCO2
        # Clean SCO column and map to friendly names
        if "SCO" in df.columns:
            cleaned_sco = df["SCO"].map(_norm_key)
            df.insert(4, "SCO2", cleaned_sco.map(SCO_MAP).fillna(""))

        # 4) Coerce ONLY the required named date columns (no guessing)
        df = coerce_named_date_columns(df)

        # 5) Keep track of source file (optional)
        df["_source_file"] = f.name

        frames.append(df)

    unified = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    st.success(f"Unified {len(files)} file(s), {len(unified):,} rows.")
    if not unified.empty:
        st.dataframe(unified.head(50))
        # --- Show unmapped SCO values (missing SCO2) ---
        if "SCO2" in unified.columns:
            missing_sco = unified[unified["SCO2"].isna() | (unified["SCO2"].astype(str).str.strip() == "")]
            if not missing_sco.empty:
                st.warning(f"{len(missing_sco)} rows have no SCO match. Review below:")
                st.dataframe(
                    missing_sco[["SCO", "Facility Code", "Begin Date", "End Date"]].head(50),
                    use_container_width=True
                )
                # Show exact raw SCO strings that didn't match (helps maintain the map)
                raw_vals = sorted(set(missing_sco["SCO"].astype(str)))
                st.caption("Unmapped SCO raw values (exact):")
                st.code("\n".join(repr(v) for v in raw_vals), language="text")
            else:
                st.success("All SCO values successfully mapped ✅")

    # Note: Export handles date formatting; no coercion here

    # Export
    default_name = f"unified_{pd.Timestamp.now():%Y%m%d_%H%M}.xlsx"
    blob = export_xlsx_bytes(unified, filename=default_name, base_dir=BASE)
    st.download_button(
        label=f"Download {default_name}",
        data=blob,
        file_name=default_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.divider()
st.write("Made In Texas 🇨🇱")