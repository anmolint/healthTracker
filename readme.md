# Health Tracker Agent

A conversational AI agent that logs your daily health metrics (weight, steps, blood sugar) to Google Sheets and generates charts on demand.

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up Google Sheets API

**a. Create a Google Cloud project:**
1. Go to https://console.cloud.google.com
2. Create a new project (or use existing)
3. Enable the **Google Sheets API**

**b. Create a Service Account:**
1. Go to IAM & Admin → Service Accounts
2. Click "Create Service Account"
3. Give it a name (e.g. `health-agent`)
4. Click "Create and Continue" → Done
5. Click the service account → Keys tab → Add Key → JSON
6. Download the JSON file → rename it `credentials.json`
7. Place `credentials.json` in this folder

**c. Create your Google Sheet:**
1. Go to https://sheets.google.com and create a new sheet
2. Name the first tab/sheet exactly: `HealthData`
3. Copy the Sheet ID from the URL:
   - URL: `https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit`
4. Share the sheet with your service account email (found in credentials.json as `client_email`) — give it **Editor** access

### 3. Set environment variables

```bash
export ANTHROPIC_API_KEY="your_anthropic_api_key"
export GOOGLE_SHEET_ID="your_google_sheet_id"
export GOOGLE_CREDENTIALS_PATH="credentials.json"  # or full path
```

Or create a `.env` file and load it.

---

## Run

```bash
python agent.py
```

---

## Usage Examples

**Log daily stats:**
```
You: Today my weight is 72.5 kg, steps were 9200, blood sugar 98 mg/dL
```

**Ask for charts:**
```
You: Show me a line chart of my blood sugar for the last 2 weeks
You: Bar chart of my steps this month
You: Scatter plot of my weight over 30 days
```

**Ask for insights:**
```
You: What's my average blood sugar this week?
You: Am I hitting 10k steps consistently?
You: What's my weight trend over the last month?
```

**Import Google Fit history (from Google Takeout):**
```
You: Import my Google Fit data from ~/Downloads/Daily Summaries.csv
You: Preview my Google Fit CSV at ~/Downloads/Daily Summaries.csv (dry run, don't write yet)
```

> **How to export from Google Fit:**
> 1. Go to https://takeout.google.com → select **Fit only** → Export once
> 2. Unzip and find: `Takeout/Fit/Daily activity metrics/Daily Summaries.csv`
> 3. Tell the agent the path to that file

---

## File Structure

```
health-agent/
├── agent.py             # Main chat loop + Claude integration
├── sheets.py            # Google Sheets read/write + chart generation
├── googlefit_import.py  # Google Fit CSV import tool
├── requirements.txt
├── credentials.json     # ← you add this (keep secret!)
└── README.md
```

> ⚠️ Never commit `credentials.json` to git. Add it to `.gitignore`.
