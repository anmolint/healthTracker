"""
sheets.py — Google Sheets I/O and chart generation for Health Tracker Agent.
"""

import os
import json
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
# Column indices (1-based in Sheets, 0-based here after list conversion)
COL_DATE = 0
COL_WEIGHT = 1
COL_STEPS = 2
COL_BLOOD_SUGAR = 3
HEADERS = ["Date", "Weight (kg)", "Steps", "Blood Sugar (mg/dL)"]

METRIC_COL = {
    "weight": COL_WEIGHT,
    "steps": COL_STEPS,
    "blood_sugar": COL_BLOOD_SUGAR,
    "blood sugar": COL_BLOOD_SUGAR,
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
    """Open and return the HealthData worksheet, creating headers if needed."""
    client = _authenticate()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise EnvironmentError("GOOGLE_SHEET_ID environment variable is not set.")

    spreadsheet = client.open_by_key(sheet_id)

    try:
        ws = spreadsheet.worksheet(SHEET_TAB)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SHEET_TAB, rows=1000, cols=10)

    # Ensure header row exists
    existing = ws.row_values(1)
    if not existing or existing[0] != "Date":
        ws.insert_row(HEADERS, index=1)

    return ws


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def append_row(
    date: str | None = None,
    weight: float | None = None,
    steps: int | None = None,
    blood_sugar: float | None = None,
) -> str:
    """Append a health metric row to the sheet. Returns a confirmation string."""
    ws = init_sheet()

    if date is None:
        date = datetime.date.today().isoformat()

    row = [
        date,
        weight if weight is not None else "",
        steps if steps is not None else "",
        blood_sugar if blood_sugar is not None else "",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")

    parts = []
    if weight is not None:
        parts.append(f"weight {weight} kg")
    if steps is not None:
        parts.append(f"{steps:,} steps")
    if blood_sugar is not None:
        parts.append(f"blood sugar {blood_sugar} mg/dL")

    return f"✅ Logged for {date}: {', '.join(parts)}."


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
            f"Unknown metric '{metric}'. Choose from: weight, steps, blood_sugar."
        )

    all_rows = ws.get_all_values()
    if len(all_rows) <= 1:
        return []

    data_rows = all_rows[1:]  # skip header
    results = []
    for row in data_rows:
        if len(row) <= col_idx:
            continue
        raw_val = row[col_idx].strip()
        if not raw_val:
            continue
        try:
            value = float(raw_val)
            date_str = row[COL_DATE].strip()
            results.append({"date": date_str, "value": value})
        except ValueError:
            continue

    # Keep only the last `days` entries
    return results[-days:]


def get_summary_stats(metric: str, days: int = 7) -> dict:
    """Return basic stats for a metric over the last N days."""
    records = read_data(metric, days)
    if not records:
        return {"count": 0, "average": None, "min": None, "max": None}

    values = [r["value"] for r in records]
    return {
        "count": len(values),
        "average": round(sum(values) / len(values), 2),
        "min": min(values),
        "max": max(values),
        "start_date": records[0]["date"],
        "end_date": records[-1]["date"],
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

CHART_LABELS = {
    "weight": "Weight (kg)",
    "steps": "Steps",
    "blood_sugar": "Blood Sugar (mg/dL)",
    "blood sugar": "Blood Sugar (mg/dL)",
}

CHART_COLORS = {
    "weight": "#4f86c6",
    "steps": "#6bbf59",
    "blood_sugar": "#e07b54",
    "blood sugar": "#e07b54",
}


def generate_chart(chart_type: str, metric: str, days: int = 14) -> str:
    """
    Generate a chart and save it as a PNG.

    Parameters
    ----------
    chart_type : 'line' | 'bar' | 'scatter'
    metric     : 'weight' | 'steps' | 'blood_sugar'
    days       : how many recent data-points to include

    Returns
    -------
    Absolute path to the saved PNG file.
    """
    records = read_data(metric, days)
    if not records:
        raise ValueError(f"No data found for metric '{metric}' in the last {days} days.")

    # Parse dates
    dates = []
    for r in records:
        try:
            dates.append(datetime.datetime.strptime(r["date"], "%Y-%m-%d"))
        except ValueError:
            dates.append(datetime.datetime.fromisoformat(r["date"]))

    values = [r["value"] for r in records]
    label = CHART_LABELS.get(metric.lower(), metric)
    color = CHART_COLORS.get(metric.lower(), "#888888")
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
        ax.scatter(dates, values, color=color, s=60, alpha=0.85, edgecolors="white", linewidths=0.5)
    else:
        raise ValueError(f"Unknown chart type '{chart_type}'. Choose: line, bar, scatter.")

    # Styling
    for spine in ax.spines.values():
        spine.set_edgecolor("#444466")
    ax.tick_params(colors="#ccccdd", labelsize=9)
    ax.xaxis.label.set_color("#ccccdd")
    ax.yaxis.label.set_color("#ccccdd")
    ax.title.set_color("#ffffff")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=30)
    ax.set_xlabel("Date", color="#aaaacc")
    ax.set_ylabel(label, color="#aaaacc")
    ax.set_title(f"{label} — last {len(records)} entries ({chart_type} chart)", color="#ffffff", fontsize=13)
    ax.grid(True, color="#333355", linestyle="--", linewidth=0.6, alpha=0.7)

    # Save
    CHARTS_DIR.mkdir(exist_ok=True)
    filename = CHARTS_DIR / f"{metric.replace(' ', '_')}_{chart_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.tight_layout()
    plt.savefig(filename, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)

    return str(filename.resolve())
