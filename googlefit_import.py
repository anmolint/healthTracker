"""
googlefit_import.py — Parse Google Fit CSV exports (from Google Takeout) and
import them into the Health Tracker Google Sheet.

How to export from Google Fit:
  1. Go to https://takeout.google.com
  2. Deselect all → select "Fit" only
  3. Choose "All time", export once, download the .zip
  4. Unzip and find: Takeout/Fit/Daily activity metrics/Daily Summaries.csv
     (or any per-day CSV under "Daily Aggregations/")
  5. Pass that file path to the agent: "import my Google Fit CSV from ~/Downloads/Daily Summaries.csv"
"""

import csv
import datetime
from pathlib import Path
from sheets import append_row

# ---------------------------------------------------------------------------
# Column name aliases — Fit exports can differ slightly between regions/dates
# ---------------------------------------------------------------------------

# Possible column names for the date field
DATE_COLS = ["Start time", "Date", "start_time", "Start Time"]

# Possible column names for step count
STEPS_COLS = ["Step count", "Steps", "step_count", "Step Count"]

# Possible column names for weight (kg)
WEIGHT_COLS = [
    "Average weight (kg)", "Weight (kg)", "weight_kg",
    "Average weight", "Weight",
]

# Possible column names for weight in lbs (will be converted)
WEIGHT_LBS_COLS = [
    "Average weight (lbs)", "Weight (lbs)", "weight_lbs",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_col(headers: list[str], candidates: list[str]) -> str | None:
    """Return the first header that matches any candidate name (case-insensitive)."""
    lower_headers = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in lower_headers:
            return lower_headers[c.lower()]
    return None


def _parse_date(raw: str) -> str | None:
    """Try to parse a date string into YYYY-MM-DD; return None on failure."""
    raw = raw.strip()
    # Formats seen in Google Fit exports:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(raw[:len(fmt)], fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    # Try isoformat with timezone suffix e.g. "2024-03-01T00:00:00+05:30"
    try:
        return datetime.datetime.fromisoformat(raw).date().isoformat()
    except (ValueError, TypeError):
        return None


def _safe_float(val: str) -> float | None:
    try:
        f = float(val.strip())
        return f if f > 0 else None
    except (ValueError, AttributeError):
        return None


def _safe_int(val: str) -> int | None:
    try:
        i = int(float(val.strip()))
        return i if i > 0 else None
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Core import function
# ---------------------------------------------------------------------------

def import_fit_csv(file_path: str, dry_run: bool = False) -> dict:
    """
    Parse a Google Fit CSV export and import rows into Google Sheets.

    Parameters
    ----------
    file_path : str
        Path to the CSV file (e.g. "Daily Summaries.csv" or a daily aggregation CSV).
    dry_run   : bool
        If True, parse and return stats without writing to Google Sheets.

    Returns
    -------
    dict with keys:
        rows_found    : int   — data rows found in the CSV
        rows_imported : int   — rows successfully written to Sheets
        rows_skipped  : int   — rows skipped (no usable data / bad date)
        dates         : list  — list of date strings imported
        errors        : list  — list of error strings for skipped rows
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Could not find the CSV file at: {path}\n"
            "Please double-check the path and try again."
        )

    results = {
        "rows_found": 0,
        "rows_imported": 0,
        "rows_skipped": 0,
        "dates": [],
        "errors": [],
    }

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Detect column positions
        date_col    = _find_col(headers, DATE_COLS)
        steps_col   = _find_col(headers, STEPS_COLS)
        weight_col  = _find_col(headers, WEIGHT_COLS)
        weight_lbs_col = _find_col(headers, WEIGHT_LBS_COLS) if not weight_col else None

        if not date_col:
            raise ValueError(
                f"Cannot find a date column in this CSV.\n"
                f"Detected columns: {', '.join(headers)}\n"
                "Expected one of: " + ", ".join(DATE_COLS)
            )

        for row in reader:
            results["rows_found"] += 1

            # Parse date
            raw_date = row.get(date_col, "").strip()
            date_str = _parse_date(raw_date)
            if not date_str:
                results["rows_skipped"] += 1
                results["errors"].append(f"Row {results['rows_found']}: could not parse date '{raw_date}'")
                continue

            # Parse steps
            steps = None
            if steps_col:
                steps = _safe_int(row.get(steps_col, ""))

            # Parse weight
            weight = None
            if weight_col:
                weight = _safe_float(row.get(weight_col, ""))
            elif weight_lbs_col:
                lbs = _safe_float(row.get(weight_lbs_col, ""))
                if lbs:
                    weight = round(lbs * 0.453592, 2)  # lbs → kg

            # Skip rows that have no usable metric data
            if steps is None and weight is None:
                results["rows_skipped"] += 1
                continue

            # Write to Google Sheets (unless dry run)
            if not dry_run:
                append_row(date=date_str, weight=weight, steps=steps)

            results["rows_imported"] += 1
            results["dates"].append(date_str)

    return results


def import_fit_csv_summary(file_path: str, dry_run: bool = False) -> str:
    """
    Human-readable wrapper around import_fit_csv for the agent tool.
    Returns a formatted summary string.
    """
    stats = import_fit_csv(file_path, dry_run=dry_run)

    prefix = "🔍 [DRY RUN] " if dry_run else ""
    lines = [
        f"{prefix}✅ Google Fit import complete!",
        f"  • Rows found in CSV : {stats['rows_found']}",
        f"  • Rows imported     : {stats['rows_imported']}",
        f"  • Rows skipped      : {stats['rows_skipped']}",
    ]
    if stats["dates"]:
        lines.append(f"  • Date range        : {stats['dates'][0]} → {stats['dates'][-1]}")
    if stats["errors"]:
        lines.append(f"\n⚠️  Parse warnings ({len(stats['errors'])}):")
        for e in stats["errors"][:5]:  # cap at 5 to avoid flooding
            lines.append(f"    - {e}")
        if len(stats["errors"]) > 5:
            lines.append(f"    ... and {len(stats['errors']) - 5} more.")
    return "\n".join(lines)
