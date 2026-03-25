"""
sheets.py — Google Sheets I/O and chart generation for Health Tracker Agent.
"""

import os
import datetime
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import matplotlib
matplotlib.use("Agg")  # headless backend; switch to TkAgg / MacOSX for interactive
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHEET_TAB = "HealthData"
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

COL_DATE        = 0
COL_WEIGHT      = 1
COL_STEPS       = 2
COL_BLOOD_SUGAR = 3
COL_DISTANCE    = 4
COL_HEART_PTS   = 5

HEADERS = ["Date", "Weight (kg)", "Steps", "Blood Sugar (mg/dL)", "Distance (m)", "Heart Points"]

METRIC_COL = {
    "weight":       COL_WEIGHT,
    "steps":        COL_STEPS,
    "blood_sugar":  COL_BLOOD_SUGAR,
    "blood sugar":  COL_BLOOD_SUGAR,
    "distance":     COL_DISTANCE,
    "heart_points": COL_HEART_PTS,
    "heart points": COL_HEART_PTS,
}

CHARTS_DIR = Path("charts")


# ---------------------------------------------------------------------------
# Auth & Sheet initialisation
# ---------------------------------------------------------------------------

def _authenticate():
    """Return an authenticated gspread client."""
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, SCOPES)
    return gspread.authorize(creds)


def init_sheet():
    """Open and return the HealthData worksheet, creating/updating headers if needed."""
    client = _authenticate()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise EnvironmentError("GOOGLE_SHEET_ID environment variable is not set.")

    spreadsheet = client.open_by_key(sheet_id)

    try:
        ws = spreadsheet.worksheet(SHEET_TAB)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SHEET_TAB, rows=1000, cols=10)

    # Update header row if new columns are missing
    existing = ws.row_values(1)
    if not existing or existing[0] != "Date":
        ws.insert_row(HEADERS, index=1)
    elif existing != HEADERS:
        # Extend headers in place without touching existing data rows
        ws.update("A1", [HEADERS])

    return ws


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

def clear_sheet() -> str:
    """
    Delete all data rows from the sheet, keeping the header row intact.
    Returns a confirmation string.
    """
    ws = init_sheet()
    all_rows = ws.get_all_values()
    data_row_count = len(all_rows) - 1  # exclude header
    if data_row_count <= 0:
        return "Sheet is already empty."

    # Clear everything then restore header
    ws.clear()
    ws.insert_row(HEADERS, index=1)
    return f"🗑️ Cleared {data_row_count} rows from the sheet."


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def _build_row(
    date, weight, steps, blood_sugar, distance, heart_points
) -> list:
    return [
        date,
        weight       if weight       is not None else "",
        steps        if steps        is not None else "",
        blood_sugar  if blood_sugar  is not None else "",
        distance     if distance     is not None else "",
        heart_points if heart_points is not None else "",
    ]


def append_row(
    date: str | None = None,
    weight: float | None = None,
    steps: int | None = None,
    blood_sugar: float | None = None,
    distance: float | None = None,
    heart_points: float | None = None,
    # Silently ignore fields the sheet doesn't store (calories, move_minutes)
    **_ignored,
) -> str:
    """Append a single health metric row. Used for manual day-by-day logging."""
    ws = init_sheet()

    if date is None:
        date = datetime.date.today().isoformat()

    ws.append_row(
        _build_row(date, weight, steps, blood_sugar, distance, heart_points),
        value_input_option="USER_ENTERED",
    )

    parts = []
    if weight       is not None: parts.append(f"weight {weight} kg")
    if steps        is not None: parts.append(f"{steps:,} steps")
    if blood_sugar  is not None: parts.append(f"blood sugar {blood_sugar} mg/dL")
    if distance     is not None: parts.append(f"distance {distance:.0f} m")
    if heart_points is not None: parts.append(f"{heart_points} heart points")

    return f"✅ Logged for {date}: {', '.join(parts)}."


def batch_append_rows(records: list[dict]) -> str:
    """
    Write multiple rows in a single API call. Used for bulk imports.

    Each dict in `records` may contain: date, weight, steps, blood_sugar,
    distance, heart_points (all optional except date).

    Returns a confirmation string.
    """
    if not records:
        return "No records to write."

    ws = init_sheet()

    rows = [
        _build_row(
            r.get("date", datetime.date.today().isoformat()),
            r.get("weight"),
            r.get("steps"),
            r.get("blood_sugar"),
            r.get("distance"),
            r.get("heart_points"),
        )
        for r in records
    ]

    ws.append_rows(rows, value_input_option="USER_ENTERED")
    return f"✅ Batch wrote {len(rows)} rows in a single API call."


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_data(metric: str, days: int = 30) -> list[dict]:
    """
    Read the last `days` rows that contain a value for `metric`.
    Returns a list of {date, value} dicts sorted oldest → newest.
    """
    ws = init_sheet()
    metric_key = metric.lower().strip()
    col_idx = METRIC_COL.get(metric_key)
    if col_idx is None:
        raise ValueError(
            f"Unknown metric '{metric}'. "
            f"Choose from: weight, steps, blood_sugar, distance, heart_points."
        )

    all_rows = ws.get_all_values()
    if len(all_rows) <= 1:
        return []

    results = []
    for row in all_rows[1:]:  # skip header
        if len(row) <= col_idx:
            continue
        raw_val = row[col_idx].strip()
        if not raw_val:
            continue
        try:
            results.append({"date": row[COL_DATE].strip(), "value": float(raw_val)})
        except ValueError:
            continue

    return results[-days:]


def get_summary_stats(metric: str, days: int = 7) -> dict:
    """Return basic stats for a metric over the last N days."""
    records = read_data(metric, days)
    if not records:
        return {"count": 0, "average": None, "min": None, "max": None}

    values = [r["value"] for r in records]
    return {
        "count":      len(values),
        "average":    round(sum(values) / len(values), 2),
        "min":        min(values),
        "max":        max(values),
        "start_date": records[0]["date"],
        "end_date":   records[-1]["date"],
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

CHART_LABELS = {
    "weight":       "Weight (kg)",
    "steps":        "Steps",
    "blood_sugar":  "Blood Sugar (mg/dL)",
    "blood sugar":  "Blood Sugar (mg/dL)",
    "distance":     "Distance (m)",
    "heart_points": "Heart Points",
    "heart points": "Heart Points",
}

CHART_COLORS = {
    "weight":       "#4f86c6",
    "steps":        "#6bbf59",
    "blood_sugar":  "#e07b54",
    "blood sugar":  "#e07b54",
    "distance":     "#c084fc",
    "heart_points": "#f472b6",
    "heart points": "#f472b6",
}


def generate_chart(chart_type: str, metric: str, days: int = 14) -> str:
    """
    Generate a chart and save it as a PNG.

    Parameters
    ----------
    chart_type : 'line' | 'bar' | 'scatter'
    metric     : 'weight' | 'steps' | 'blood_sugar' | 'distance' | 'heart_points'
    days       : how many recent data-points to include

    Returns
    -------
    Absolute path to the saved PNG file.
    """
    records = read_data(metric, days)
    if not records:
        raise ValueError(f"No data found for metric '{metric}' in the last {days} days.")

    dates = []
    for r in records:
        try:
            dates.append(datetime.datetime.strptime(r["date"], "%Y-%m-%d"))
        except ValueError:
            dates.append(datetime.datetime.fromisoformat(r["date"]))

    values     = [r["value"] for r in records]
    label      = CHART_LABELS.get(metric.lower(), metric)
    color      = CHART_COLORS.get(metric.lower(), "#888888")
    chart_type = chart_type.lower().strip()

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#1e1e2e")
    ax.set_facecolor("#1e1e2e")

    if chart_type == "line":
        ax.plot(dates, values, color=color, linewidth=2.5, marker="o", markersize=5)
        ax.fill_between(dates, values, alpha=0.15, color=color)
    elif chart_type == "bar":
        ax.bar(dates, values, color=color, width=0.6, alpha=0.85)
    elif chart_type == "scatter":
        ax.scatter(dates, values, color=color, s=60, alpha=0.85,
                   edgecolors="white", linewidths=0.5)
    else:
        raise ValueError(f"Unknown chart type '{chart_type}'. Choose: line, bar, scatter.")

    for spine in ax.spines.values():
        spine.set_edgecolor("#444466")
    ax.tick_params(colors="#ccccdd", labelsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=30)
    ax.set_xlabel("Date", color="#aaaacc")
    ax.set_ylabel(label, color="#aaaacc")
    ax.set_title(
        f"{label} — last {len(records)} entries ({chart_type} chart)",
        color="#ffffff", fontsize=13
    )
    ax.grid(True, color="#333355", linestyle="--", linewidth=0.6, alpha=0.7)

    CHARTS_DIR.mkdir(exist_ok=True)
    filename = CHARTS_DIR / (
        f"{metric.replace(' ', '_')}_{chart_type}_"
        f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    )
    plt.tight_layout()
    plt.savefig(filename, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)

    return str(filename.resolve())