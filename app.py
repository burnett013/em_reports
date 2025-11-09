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
    detected_overall_period,  # noqa: E402
)

# ---------- Config ----------
BASE = Path("exports")

# ---------- App ----------
st.set_page_config(page_title="EM Reports", layout="wide")
st.title("EM Report Compiler")
st.divider()
st.subheader("1 | Detailed Reports")

st.sidebar.header("Version: v2.0 (11/9/2025)")
st.sidebar.divider()

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

# ---- Summary uploader block (moved up) ----
st.subheader("2 | Summary Reports")

# ---- Summary report workflow ----
summary_files = st.file_uploader(
    "Summary CSV files",
    type=["csv"],
    accept_multiple_files=True,
    key="summary_uploader",
    help="Drop the 1-row Summary CSVs exported from VA (any number)."
)
summary_files = summary_files[:100] if summary_files else []

# From and To dates detected from filenames (Detail and Summary)
st.sidebar.header("Detail Date Range:")
auto_period_detail = detected_overall_period(files)
if auto_period_detail:
    d_from, d_to = auto_period_detail
    st.sidebar.subheader(f"{d_from:%m/%d/%Y} – {d_to:%m/%d/%Y}")
else:
    st.sidebar.caption("Upload Detail CSVs to detect range.")

st.sidebar.divider()
st.sidebar.header("Summary Date Range:")
auto_period_summary = detected_overall_period(summary_files)
if auto_period_summary:
    s_from, s_to = auto_period_summary
    st.sidebar.subheader(f"{s_from:%m/%d/%Y} – {s_to:%m/%d/%Y}")
else:
    st.sidebar.caption("Upload Summary CSVs to detect range.")

st.subheader("Build unified table(s) and export")
if st.button("Build & Export XLSX EM Report", use_container_width=True, disabled=not (files or summary_files)):
    # ---------- DETAIL PIPELINE ----------
    frames: List[pd.DataFrame] = []
    total_skipped = 0
    per_file_stats = []

    # Determine a sensible fallback period if a filename is missing dates
    fallback_from, fallback_to = None, None
    if auto_period_detail:
        fallback_from, fallback_to = auto_period_detail
    else:
        today = pd.Timestamp.today().normalize()
        fallback_from, fallback_to = today, today

    for f in files or []:
        # some environments need a rewind before each read
        try:
            f.seek(0)
        except Exception:
            pass

        df, skipped = robust_read_csv(f)
        total_skipped += skipped

        # Dates from filename with fallback to detected overall or today
        f_from, f_to = extract_dates_from_filename(getattr(f, "name", ""))
        from_dt = pd.to_datetime(f_from or fallback_from)
        to_dt   = pd.to_datetime(f_to   or fallback_to)

        # New columns
        year_val  = from_dt.year
        month_val = from_dt.strftime("%b")
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
        df["_source_file"] = getattr(f, "name", "")

        frames.append(df)
        per_file_stats.append({"file": getattr(f, "name", ""), "rows": int(df.shape[0]), "cols": int(df.shape[1]), "skipped": int(skipped)})

    unified_detail = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    detail_stats = {"total_skipped": total_skipped, "per_file": per_file_stats}

    if total_skipped:
        st.warning(f"⚠️ Detail: a total of **{total_skipped}** malformed row(s) were skipped across all files.")
    else:
        st.success("✅ Detail: no malformed rows detected in uploaded files.")

    st.caption("Detail per-file parse summary")
    if per_file_stats:
        st.dataframe(pd.DataFrame(per_file_stats))

    if not unified_detail.empty:
        st.success(f"Detail: unified {len(files)} file(s), {len(unified_detail):,} rows.")
        st.dataframe(unified_detail.head(50))
        if 'SCO2' in unified_detail.columns:
            missing_sco = unified_detail[unified_detail['SCO2'].isna() | (unified_detail['SCO2'].astype(str).str.strip() == "")]
            if not missing_sco.empty:
                st.warning(f"{len(missing_sco)} rows have no SCO match. Review below:")
                st.dataframe(missing_sco[["SCO", "Facility Code", "Begin Date", "End Date"]].head(50))

    # ---------- SUMMARY PIPELINE ----------
    sum_frames: List[pd.DataFrame] = []
    sum_skipped = 0
    sum_stats = []

    # Determine fallback period once
    s_fallback_from, s_fallback_to = (auto_period_summary if auto_period_summary else (pd.Timestamp.today().normalize(), pd.Timestamp.today().normalize()))

    for f in summary_files:
        try:
            f.seek(0)
        except Exception:
            pass

        df_s, skipped = robust_read_csv(f)
        sum_skipped += skipped

        f_from, f_to = extract_dates_from_filename(getattr(f, "name", ""))
        from_dt = pd.to_datetime(f_from or s_fallback_from)
        to_dt   = pd.to_datetime(f_to   or s_fallback_to)

        df_s.insert(0, "Year",  from_dt.year)
        df_s.insert(1, "Month", from_dt.strftime("%b"))
        df_s.insert(2, "From",  from_dt)
        df_s.insert(3, "To",    to_dt)

        if "SCO" in df_s.columns:
            cleaned_sco = df_s["SCO"].map(_norm_key)
            df_s.insert(4, "SCO2", cleaned_sco.map(SCO_MAP).fillna(""))

        df_s = coerce_named_date_columns(df_s)
        df_s["_source_file"] = getattr(f, "name", "")
        sum_frames.append(df_s)
        sum_stats.append({"file": getattr(f, "name", ""), "rows": int(df_s.shape[0]), "cols": int(df_s.shape[1]), "skipped": int(skipped)})

    unified_summary = pd.concat(sum_frames, ignore_index=True) if sum_frames else pd.DataFrame()
    summary_stats = {"total_skipped": sum_skipped, "per_file": sum_stats}

    if sum_skipped:
        st.warning(f"⚠️ Summary: {sum_skipped} malformed row(s) were skipped across all files.")
    else:
        st.success("✅ Summary: no malformed rows detected.")

    st.caption("Summary per-file parse stats")
    if sum_stats:
        st.dataframe(pd.DataFrame(sum_stats))

    if not unified_summary.empty:
        st.success(f"Summary: unified {len(summary_files)} file(s), {len(unified_summary):,} rows.")
        st.dataframe(unified_summary.head(30))

    # ---------- ONE FILE / TWO SHEETS EXPORT ----------
    # If neither dataset exists, do nothing
    if unified_detail.empty and unified_summary.empty:
        st.info("Nothing to export yet — upload Detail and/or Summary CSVs.")
    else:
        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            wb = writer.book
            date_fmt = wb.add_format({"num_format": "mm/dd/yy"})

            def write_sheet(df: pd.DataFrame, sheet_name: str):
                # Convert datetime columns to date-only (no time)
                date_cols = ["From", "To", "Begin Date", "End Date", "Submission Date", "Amendment Effective Date"]
                for col in date_cols:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
                df.to_excel(writer, index=False, sheet_name=sheet_name)
                ws = writer.sheets[sheet_name]
                # auto width-ish
                for idx, col in enumerate(df.columns):
                    # set a reasonable width; widen date columns and apply date format
                    width = max(10, min(22, int(df[col].astype(str).str.len().quantile(0.9)) + 2))
                    if col in ["From", "To", "Begin Date", "End Date", "Submission Date", "Amendment Effective Date"]:
                        ws.set_column(idx, idx, 12, date_fmt)
                    else:
                        ws.set_column(idx, idx, width)

            if not unified_detail.empty:
                write_sheet(unified_detail, "Detail")
            if not unified_summary.empty:
                write_sheet(unified_summary, "Summary")

        output.seek(0)
        combined_name = f"emr_{pd.Timestamp.now():%Y%m%d_%H%M}.xlsx"
        st.download_button(
            label=f"Download {combined_name}",
            data=output.getvalue(),
            file_name=combined_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

st.divider()
st.markdown("<h4 style='text-align: center;'>Made In Texas 🇨🇱</h4>", unsafe_allow_html=True)