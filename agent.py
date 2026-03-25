import os
import sys
import json
from dotenv import load_dotenv
import anthropic

from sheets import append_row, read_data, get_summary_stats, generate_chart, clear_sheet
from googlefit_import import import_consolidated, import_summary

load_dotenv()

# System prompt
SYSTEM_PROMPT = """You are a helpful Health Tracker Assistant.
Your job is to help the user log their daily health metrics (weight, steps, blood sugar) to Google Sheets,
and generate charts and insights on demand based on their stored data.

Use the provided tools to:
1. `append_row`: Log new health data (one row, one API call).
2. `read_data`: Read historical data for a specific metric.
3. `get_summary_stats`: Get basic statistics for a metric over a time period.
4. `generate_chart`: Generate a chart (line, bar, scatter) and save it as a PNG image.
5. `import_google_fit_csv`: Import historical data from a Google Fit CSV export and append to existing data. All rows are written in a single batch API call.
6. `bulk_import_google_fit_csv`: Clear all existing sheet data first, then import from Google Fit CSV using a single batch API call. Use this when the user says 'bulk import', 'replace all data', or 'start fresh'. Always confirm with the user before running this since existing data cannot be recovered.

When a chart is generated, inform the user where it was saved.
When the user wants to import Google Fit data, ask for the CSV file path if they haven't provided one.
If you need more information to log data or generate a chart, ask the user.
"""

# Tool schemas definition
TOOLS = [
    {
        "name": "append_row",
        "description": "Append a health metric row to the sheet. Use this to log daily stats. Returns a confirmation string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format. If not provided, defaults to today."
                },
                "weight": {
                    "type": "number",
                    "description": "Weight in kg."
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of steps taken."
                },
                "blood_sugar": {
                    "type": "number",
                    "description": "Blood sugar level in mg/dL."
                }
            }
        }
    },
    {
        "name": "read_data",
        "description": "Read the last `days` rows that contain a value for `metric`.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["weight", "steps", "blood_sugar", "blood sugar"],
                    "description": "The health metric to read."
                },
                "days": {
                    "type": "integer",
                    "description": "Number of recent days of data to retrieve. Default is 30."
                }
            },
            "required": ["metric"]
        }
    },
    {
        "name": "get_summary_stats",
        "description": "Return basic statistics (count, average, min, max) for a metric over the last `days` days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["weight", "steps", "blood_sugar", "blood sugar"],
                    "description": "The health metric to summarize."
                },
                "days": {
                    "type": "integer",
                    "description": "Number of recent days of data to summarize. Default is 7."
                }
            },
            "required": ["metric"]
        }
    },
    {
        "name": "generate_chart",
        "description": "Generate a chart (line, bar, or scatter) and save it as a PNG file. Returns the absolute path to the saved PNG.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["line", "bar", "scatter"],
                    "description": "Type of chart to generate."
                },
                "metric": {
                    "type": "string",
                    "enum": ["weight", "steps", "blood_sugar", "blood sugar"],
                    "description": "The health metric to chart."
                },
                "days": {
                    "type": "integer",
                    "description": "How many recent data-points to include. Default is 14."
                }
            },
            "required": ["chart_type", "metric"]
        }
    },
    {
        "name": "import_google_fit_csv",
        "description": (
            "Import historical health data from a Google Fit Daily_activity_metrics.csv "
            "export. Appends to existing sheet data without clearing it. "
            "All rows are written in a single batch API call (not one call per row). "
            "Use dry_run=true to preview without writing to Sheets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to Daily_activity_metrics.csv (e.g. '~/Downloads/Daily_activity_metrics.csv')."
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, parse and preview without writing to Sheets. Default is false."
                },
                "start_date": {
                    "type": "string",
                    "description": "Optional. Only import rows on or after this date (YYYY-MM-DD)."
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional. Only import rows on or before this date (YYYY-MM-DD)."
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "bulk_import_google_fit_csv",
        "description": (
            "Clear ALL existing data from the sheet, then import from a Google Fit "
            "Daily_activity_metrics.csv using a single batch API call. "
            "Use this when the user wants a fresh import or says 'bulk import', "
            "'replace all data', or 'start fresh'. "
            "Always confirm with the user before calling this — existing data cannot be recovered."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to Daily_activity_metrics.csv."
                },
                "start_date": {
                    "type": "string",
                    "description": "Optional. Only import rows on or after this date (YYYY-MM-DD)."
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional. Only import rows on or before this date (YYYY-MM-DD)."
                }
            },
            "required": ["file_path"]
        }
    }
]

def execute_tool(tool_name: str, tool_input: dict):
    if tool_name == "append_row":
        return append_row(**tool_input)
    elif tool_name == "read_data":
        return read_data(**tool_input)
    elif tool_name == "get_summary_stats":
        return get_summary_stats(**tool_input)
    elif tool_name == "generate_chart":
        return generate_chart(**tool_input)
    elif tool_name == "import_google_fit_csv":
        return import_summary(
            file_path=tool_input["file_path"],
            dry_run=tool_input.get("dry_run", False),
            start_date=tool_input.get("start_date"),
            end_date=tool_input.get("end_date"),
        )
    elif tool_name == "bulk_import_google_fit_csv":
        clear_result = clear_sheet()
        import_result = import_summary(
            file_path=tool_input["file_path"],
            dry_run=False,
            start_date=tool_input.get("start_date"),
            end_date=tool_input.get("end_date"),
        )
        return f"{clear_result}\n{import_result}"
    else:
        raise ValueError(f"Unknown tool: {tool_name}")

def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set. Please set it in your .env file or environment.")
        sys.exit(1)

    client = anthropic.Anthropic()

    print("🏥 Health Tracker Agent is running. Type 'exit' or 'quit' to stop.")

    messages = []

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            if not user_input.strip():
                continue

            messages.append({"role": "user", "content": user_input})

            while True:
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    tools=TOOLS,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                )

                messages.append({"role": "assistant", "content": response.content})

                tool_uses = [block for block in response.content if block.type == "tool_use"]

                for block in response.content:
                    if block.type == "text":
                        print(f"\nAgent: {block.text}")

                if not tool_uses:
                    break

                tool_results = []
                for tool_use in tool_uses:
                    try:
                        print(f"\n[Executing tool '{tool_use.name}' with inputs: {tool_use.input}]")
                        result = execute_tool(tool_use.name, tool_use.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": json.dumps({"result": result})
                        })
                    except Exception as e:
                        print(f"\n[Tool error: {str(e)}]")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Error executing {tool_use.name}: {str(e)}",
                            "is_error": True
                        })

                messages.append({"role": "user", "content": tool_results})

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {str(e)}")

if __name__ == "__main__":
    main()