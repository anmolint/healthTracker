"""
googlefit_import.py — Agent tool for importing Daily_activity_metrics.csv
(Google Fit consolidated export) into the Health Tracker Google Sheet.

Designed to be called directly by an agent. Two entry points:

  import_consolidated(file_path, dry_run, start_date, end_date) -> dict
      Returns structured data the agent can reason over.

  import_summary(file_path, dry_run, start_date, end_date) -> str
      Returns a human-readable summary string for the agent to report back.

Example agent usage:
  result = import_summary("~/Downloads/Daily_activity_metrics.csv")
  result = import_summary("~/Downloads/Daily_activity_metrics.csv", dry_run=True)
  result = import_summary("~/Downloads/Daily_activity_metrics.csv",
                          start_date="2023-01-01", end_date="2023-12-31")
"""

import csv
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Sheets integration — replace append_row with your actual implementation
# ---------------------------------------------------------------------------
try:
    from sheets import append_row, batch_append_rows
except ImportError:
    def append_row(date, steps, calories, distance, weight,
                   move_minutes=None, heart_points=None):
        parts = [f"date={date}"]
        if steps         is not None: parts.append(f"steps={steps}")
        if calories      is not None: parts.append(f"cal={calories:.1f}kcal")
        if distance      is not None: parts.append(f"dist={distance:.0f}m")
        if weight        is not None: parts.append(f"weight={weight}kg")
        if move_minutes  is not None: parts.append(f"move={move_minutes}min")
        if heart_points  is not None: parts.append(f"hp={heart_points}")
        print("  [sheets]", " | ".join(parts))

    def batch_append_rows(records):
        for r in records:
            append_row(**r)

# ---------------------------------------------------------------------------
# Column definitions — handles naming variations across exports
# ---------------------------------------------------------------------------
COLS = {
    "date":         ["Date", "date"],
    "steps":        ["Step count", "Steps", "step_count"],
    "calories":     ["Calories (kcal)", "Calories", "calories_kcal"],
    "distance":     ["Distance (m)", "Distance", "distance_m"],
    "weight_kg":    ["Average weight (kg)", "Weight (kg)", "weight_kg",
                     "Average weight", "Weight"],
    "move_minutes": ["Move Minutes count", "Move Minutes", "move_minutes"],
    "heart_points": ["Heart Points", "heart_points"],
}
WEIGHT_LBS_COLS = ["Average weight (lbs)", "Weight (lbs)", "weight_lbs"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_col(headers: list[str], candidates: list[str]) -> str | None:
    lower = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def _safe_float(val: str) -> float | None:
    try:
        f = float(str(val).strip())
        return f if f >= 0 else None
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Agent tool functions
# ---------------------------------------------------------------------------

def import_consolidated(
    file_path: str,
    dry_run: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """
    Parse Daily_activity_metrics.csv and import rows into Google Sheets.

    Parameters
    ----------
    file_path  : str        Path to Daily_activity_metrics.csv.
    dry_run    : bool       If True, parse and return stats without writing
                            to Sheets. Useful for previewing before import.
    start_date : str|None   Inclusive start date in YYYY-MM-DD format.
    end_date   : str|None   Inclusive end date in YYYY-MM-DD format.

    Returns
    -------
    dict
        rows_found    : int   — total data rows in the file
        rows_imported : int   — rows written to Sheets (or would be, if dry_run)
        rows_skipped  : int   — rows with no usable data or out of date range
        dates         : list  — sorted list of imported date strings
        errors        : list  — parse warnings for skipped rows
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path}\n"
            "Check the path and try again."
        )

    results = {
        "rows_found":    0,
        "rows_imported": 0,
        "rows_skipped":  0,
        "dates":         [],
        "errors":        [],
    }
    pending: list[dict] = []  # rows buffered for a single batch write

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        col_map = {key: _find_col(headers, candidates)
                   for key, candidates in COLS.items()}
        weight_lbs_col = (
            _find_col(headers, WEIGHT_LBS_COLS)
            if not col_map["weight_kg"] else None
        )

        if not col_map["date"]:
            raise ValueError(
                f"Cannot find a 'Date' column in {path.name}.\n"
                f"Columns found: {', '.join(headers)}"
            )

        for row in reader:
            results["rows_found"] += 1

            # --- Date ---
            date_str = row.get(col_map["date"], "").strip()
            if not date_str:
                results["rows_skipped"] += 1
                continue
            try:
                datetime.date.fromisoformat(date_str)
            except ValueError:
                results["rows_skipped"] += 1
                results["errors"].append(
                    f"Row {results['rows_found']}: unrecognised date '{date_str}'"
                )
                continue

            if start_date and date_str < start_date:
                results["rows_skipped"] += 1
                continue
            if end_date and date_str > end_date:
                results["rows_skipped"] += 1
                continue

            # --- Metrics ---
            def get(key):
                col = col_map.get(key)
                return _safe_float(row.get(col, "")) if col else None

            steps        = round(v) if (v := get("steps")) else None
            calories     = round(v, 2) if (v := get("calories")) else None
            distance     = round(v, 2) if (v := get("distance")) else None
            move_minutes = round(v) if (v := get("move_minutes")) else None
            heart_points = round(v, 1) if (v := get("heart_points")) else None

            weight = get("weight_kg")
            if weight is None and weight_lbs_col:
                lbs    = _safe_float(row.get(weight_lbs_col, ""))
                weight = round(lbs * 0.453592, 2) if lbs else None
            elif weight:
                weight = round(weight, 2)

            # Skip rows with no usable data
            if all(v is None for v in
                   [steps, calories, distance, weight, move_minutes, heart_points]):
                results["rows_skipped"] += 1
                continue

            pending.append({
                "date":         date_str,
                "steps":        steps,
                "distance":     distance,
                "weight":       weight,
                "heart_points": heart_points,
            })
            results["dates"].append(date_str)

    # Single API call for all rows instead of one call per row
    if not dry_run and pending:
        batch_append_rows(pending)

    results["rows_imported"] = len(pending)
    return results


def import_summary(
    file_path: str,
    dry_run: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """
    Human-readable summary of a consolidated import run.
    Returns a string the agent can report directly to the user.

    Parameters match import_consolidated().
    """
    stats = import_consolidated(
        file_path, dry_run=dry_run,
        start_date=start_date, end_date=end_date
    )

    prefix = "[DRY RUN] " if dry_run else ""
    lines = [
        f"{prefix}Google Fit import complete.",
        f"  Rows found:     {stats['rows_found']}",
        f"  Rows imported:  {stats['rows_imported']}",
        f"  Rows skipped:   {stats['rows_skipped']}",
    ]
    if stats["dates"]:
        lines.append(f"  Date range:     {stats['dates'][0]} → {stats['dates'][-1]}")
    if stats["errors"]:
        lines.append(f"\nWarnings ({len(stats['errors'])}):")
        for e in stats["errors"][:5]:
            lines.append(f"  - {e}")
        if len(stats["errors"]) > 5:
            lines.append(f"  ... and {len(stats['errors']) - 5} more.")
    return "\n".join(lines)