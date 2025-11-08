from __future__ import annotations

from pathlib import Path
from typing import List
import pandas as pd
import streamlit as st

# ---------- Utilities ----------
from functions.functions import (
    coerce_named_date_columns,
    export_xlsx_bytes,
    extract_dates_from_filename,
    robust_read_csv,
)

# ---------- Config ----------
# BASE = Path("/Users/andyburnett/Library/Mobile Documents/com~apple~CloudDocs/Desktop/X03.27.25/OVS/Special Projects/em_report_project/v5")
BASE = Path("exports")

# ---------- App ----------
st.set_page_config(page_title="EM Reports", layout="wide")
st.title("EM Report Compiler")
st.divider()
st.subheader("Detailed Reports - v1.0")

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

st.subheader("🔎 Diagnose uploaded CSVs")
if st.button("Run diagnostics", use_container_width=True, disabled=not files):
    for f in files:
        name = getattr(f, "name", "unknown")
        st.write(f"**{name}**")
        try:
            # Try tolerant read
            df, skipped = robust_read_csv(f)
            st.success(f"Parsed OK — {len(df):,} rows, {len(df.columns)} cols")
            if skipped:
                st.warning(f"⚠️ {f.name}: {skipped} malformed row(s) detected (skipped).")
        except Exception as e:
            st.error(f"Failed to parse: {name}")
            st.code(str(e))
            # Pinpoint structural issues (column count mismatches)
            diag = find_bad_rows(f)
            st.write({"delimiter": diag["delimiter"], "expected_cols": diag["expected_cols"]})
            if diag["bad_rows"]:
                st.warning(f"First {len(diag['bad_rows'])} mismatched rows:")
                for line_no, found_cols, snippet in diag["bad_rows"][:10]:
                    st.code(f"line {line_no} | cols={found_cols} | {snippet}")
            else:
                st.info("No column-count mismatches; likely quoting/encoding issue.")

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
    total_skipped = 0
    per_file_stats = []

    for f in files:
        # some environments need a rewind before each read
        try:
            f.seek(0)
        except Exception:
            pass

        df, skipped = robust_read_csv(f)
        total_skipped += skipped

        # Dates from filename with sidebar fallback
        f_from, f_to = extract_dates_from_filename(f.name)
        from_dt = pd.to_datetime(f_from or date_from)
        to_dt   = pd.to_datetime(f_to   or date_to)

        # New columns
        year_val  = from_dt.year           # int year
        month_val = from_dt                # true date; Excel formatter will show mmm
        df.insert(0, "Year",  year_val)
        df.insert(1, "Month", month_val)
        df.insert(2, "From",  from_dt)
        df.insert(3, "To",    to_dt)

        # SCO mapping
        if "SCO" in df.columns:
            cleaned_sco = df["SCO"].map(_norm_key)
            df.insert(4, "SCO2", cleaned_sco.map(SCO_MAP).fillna(""))

        # Coerce ONLY the named date columns
        df = coerce_named_date_columns(df)

        # Track source
        df["_source_file"] = f.name

        frames.append(df)
        per_file_stats.append(
            {"file": f.name, "rows": int(df.shape[0]), "cols": int(df.shape[1]), "skipped": int(skipped)}
        )

    # Summaries
    if total_skipped:
        st.warning(f"⚠️ A total of **{total_skipped}** malformed row(s) were skipped across all files.")
    else:
        st.success("✅ No malformed rows detected in uploaded files.")

    # Optional: quick per-file table to verify all files contributed rows
    st.caption("Per-file parse summary")
    st.dataframe(pd.DataFrame(per_file_stats))

    # Build unified and show/download
    unified = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    st.success(f"Unified {len(files)} file(s), {len(unified):,} rows.")
    if not unified.empty:
        st.dataframe(unified.head(50))

        if "SCO2" in unified.columns:
            missing_sco = unified[unified["SCO2"].isna() | (unified["SCO2"].astype(str).str.strip() == "")]
            if not missing_sco.empty:
                st.warning(f"{len(missing_sco)} rows have no SCO match. Review below:")
                st.dataframe(missing_sco[["SCO", "Facility Code", "Begin Date", "End Date"]].head(50))
                raw_vals = sorted(set(missing_sco["SCO"].astype(str)))
                st.caption("Unmapped SCO raw values (exact):")
                st.code("\n".join(repr(v) for v in raw_vals), language="text")
            else:
                st.success("All SCO values successfully mapped ✅")

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