# functions/functions.py
from __future__ import annotations
import io
from typing import Optional, Tuple, List
from datetime import date
from pathlib import Path
import re
import pandas as pd
import csv

# Use your actual column names
DEFAULT_DATE_COLS: List[str] = [
    "From",
    "To",
    "Begin Date",
    "End Date",
    "Submission Date",
    "Amendment Effective Date",
]

def export_xlsx_bytes(
    df: pd.DataFrame,
    *,
    filename: str = "unified.xlsx",
    base_dir: Optional[Path] = None,
    date_cols: Optional[List[str]] = None,
) -> bytes:
    """
    Write df to in-memory Excel with real Excel date cells using the SHORT
    date format mm/dd/yy so Excel displays like 10/27/25.
    """
    cols = date_cols or [
        "From",
        "To",
        "Begin Date",
        "End Date",
        "Submission Date",
        "Amendment Effective Date",
    ]

    # 1) Ensure datetime dtype (leave as datetime64[ns]; don't .dt.date)
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # 2) Write with explicit Excel date formats so per-cell formats are correct
    output = io.BytesIO()
    with pd.ExcelWriter(
        output,
        engine="xlsxwriter",
        datetime_format="mm/dd/yy",  # applies to datetime cells
        date_format="mm/dd/yy",      # applies to date cells
    ) as writer:
        df.to_excel(writer, index=False, sheet_name="EMR - Detail")

        ws = writer.sheets["EMR - Detail"]
        wb = writer.book                          # <— add
        month_fmt = wb.add_format({"num_format": "mmm"})  # Oct, Nov, ...

            # If Month exists, re-write the Month column cells with 'mmm' format
        if "Month" in df.columns:
            mcol = df.columns.get_loc("Month")
            # Row 0 is headers in Excel; data starts at row 1
            for r, val in enumerate(df["Month"], start=1):
                if pd.notna(val):
                    ws.write_datetime(r, mcol, pd.to_datetime(val).to_pydatetime(), month_fmt)

        # Set reasonable column widths (no format object so we don't override cell formats)
        for idx, col in enumerate(df.columns):
            try:
                maxlen = int(df[col].astype(str).head(1000).str.len().max())
            except Exception:
                maxlen = 10
            width = min(max(10, maxlen + 2), 60)
            # Make date columns a bit narrower if you like
            if col == "Month":
                ws.set_column(idx, idx, 8)      # compact width for 'Oct'
            elif col in cols:
                ws.set_column(idx, idx, 12)
            else:
                ws.set_column(idx, idx, width)

    output.seek(0)
    if base_dir:
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / filename).write_bytes(output.getvalue())
    output.seek(0)
    return output.getvalue()
# --------- Filename date range parser ---------
def _norm_year(y: str) -> int:
    """Normalize 2-digit to 2000–2099; keep 4-digit as-is."""
    return int(y) if len(y) == 4 else 2000 + int(y)

def _build_date(m: str, d: str, y: str, *, dayfirst: bool = False) -> Optional[date]:
    """Build a date from strings; supports switching to day-first if you ever need it."""
    try:
        if dayfirst:
            dd, mm = int(m), int(d)  # flip if your pattern were DD.MM; kept here for parity
        else:
            mm, dd = int(m), int(d)
        yy = _norm_year(y)
        return date(yy, mm, dd)
    except ValueError:
        return None

def extract_dates_from_filename(filename: str, *, dayfirst: bool = False) -> Tuple[Optional[date], Optional[date]]:
    """
    Extract a single date or a date RANGE from the filename (before .csv).

    Supported inside name:
      - Date token: MM.DD.YY or MM.DD.YYYY (also allows '-')
      - Range: two date tokens separated by a SINGLE underscore
        e.g., 10.27.25_11.2.25.csv  or 01-01-2025_01-15-2025.csv

    Returns: (from_date, to_date), either may be None if not found.
    """
    base = filename[:-4] if filename.lower().endswith(".csv") else filename

    # RANGE with a single underscore
    range_pat = re.compile(
        r"(\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})_(\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})"
    )
    m = range_pat.search(base)
    if m:
        m1, d1, y1, m2, d2, y2 = m.groups()
        start = _build_date(m1, d1, y1, dayfirst=dayfirst)
        end   = _build_date(m2, d2, y2, dayfirst=dayfirst)
        return (start, end)

    # SINGLE date
    single_pat = re.compile(r"(\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})")
    m = single_pat.search(base)
    if m:
        m1, d1, y1 = m.groups()
        start = _build_date(m1, d1, y1, dayfirst=dayfirst)
        return (start, None)

    return (None, None)


# --------- Strict date coercion for named columns only ---------
_REQUIRED_DATE_COLS: List[str] = [
    "Begin Date",
    "End Date",
    "Submission Date",
    "Amendment Effective Date",
]

def coerce_named_date_columns(
    df: pd.DataFrame,
    *,
    dayfirst: bool = False,
    format_hint: Optional[str] = None,
) -> pd.DataFrame:
    """
    Coerce ONLY the four required columns to datetime64[ns], if they exist by exact name.
    No guessing, no positional inference.
    """
    out = df.copy()
    for col in _REQUIRED_DATE_COLS:
        if col not in out.columns:
            continue
        if format_hint:
            out[col] = pd.to_datetime(out[col], errors="coerce", format=format_hint)
        else:
            out[col] = pd.to_datetime(out[col], errors="coerce", dayfirst=dayfirst)
    return out

# Error handling ----------------------------
def sniff_delimiter(text_sample: str) -> str:
    try:
        return csv.Sniffer().sniff(text_sample, delimiters=[",",";","\t","|"]).delimiter
    except Exception:
        return ","  # fallback

def robust_read_csv(uploaded_file) -> tuple[pd.DataFrame, int]:
    """
    Defensive CSV loader:
      - detect delimiter,
      - try utf-8-sig then cp1252 (fallback replace),
      - count malformed rows (based on first N columns),
      - parse using only the first 40 columns (by position),
      - skip bad lines using engine='python'.
    Returns: (df, skipped_row_count)
    """
    raw = uploaded_file.read()
    uploaded_file.seek(0)

    # Decode text
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    # Sniff delimiter
    sample = text[:32768]
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"]).delimiter
    except Exception:
        sep = ","

    # First pass: determine header col count and count malformed rows
    lines = text.splitlines()
    reader = csv.reader(lines, delimiter=sep)

    try:
        header = next(reader)
    except StopIteration:
        return pd.DataFrame(), 0  # empty file

    total_cols = len(header)
    keep_cols = min(40, total_cols)   # <-- restrict to first 40 columns

    # Count rows that don't have at least 'keep_cols' fields
    skipped = 0
    for row in reader:
        if len(row) < keep_cols:
            skipped += 1

    # Second pass: parse with pandas, using only first 'keep_cols' columns
    # NOTE: no low_memory with python engine
    df = pd.read_csv(
        io.StringIO(text),
        sep=sep,
        engine="python",
        on_bad_lines="skip",
        usecols=range(keep_cols),   # <-- only first 40 (or fewer) columns by position
    )
    return df, skipped