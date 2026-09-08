"""
AI Verdant — Google Sheets Bridge

Mirrors every sensor reading into a Google Sheet so the raw data is
viewable/shareable without opening the app. Uses a Google Cloud
service account (no OAuth login flow needed on the device side).

SETUP (one-time):
  1. Go to console.cloud.google.com -> create a project.
  2. Enable "Google Sheets API" and "Google Drive API".
  3. Create a Service Account -> create a JSON key -> download it as
     backend/service_account.json (never commit this file).
  4. Create a Google Sheet named "AI Farming - Sensor Log" (or set
     GOOGLE_SHEET_NAME / GOOGLE_SHEET_ID in .env).
  5. Share that Sheet with the service account's email address
     (found in service_account.json as "client_email"), Editor access.
  6. pip install gspread google-auth
"""

import logging
from datetime import datetime
from config import Config

logger = logging.getLogger("ai_verdant.sheets")

_client = None
_sheet = None

HEADER_ROW = [
    "Timestamp", "Device ID", "Temperature (°C)", "Humidity (%)",
    "Soil Moisture (%)", "pH", "Water Level (cm)", "Motion Detected",
    "Overall Score",
]


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            Config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes
        )
        _client = gspread.authorize(creds)
        return _client
    except FileNotFoundError:
        logger.warning(
            "Google service account file not found at %s — Sheets sync disabled "
            "until it's added. The app will keep working off the local database.",
            Config.GOOGLE_SERVICE_ACCOUNT_FILE,
        )
        return None
    except Exception as e:
        logger.warning("Could not initialise Google Sheets client: %s", e)
        return None


def _get_sheet():
    global _sheet
    if _sheet is not None:
        return _sheet
    client = _get_client()
    if client is None:
        return None
    try:
        if Config.GOOGLE_SHEET_ID:
            spreadsheet = client.open_by_key(Config.GOOGLE_SHEET_ID)
        else:
            spreadsheet = client.open(Config.GOOGLE_SHEET_NAME)
        try:
            worksheet = spreadsheet.worksheet("Readings")
        except Exception:
            worksheet = spreadsheet.add_worksheet(title="Readings", rows=2000, cols=len(HEADER_ROW))
            worksheet.append_row(HEADER_ROW)
        # Ensure header exists
        first_row = worksheet.row_values(1)
        if first_row != HEADER_ROW:
            worksheet.update("A1", [HEADER_ROW])
        _sheet = worksheet
        return _sheet
    except Exception as e:
        logger.warning("Could not open Google Sheet: %s", e)
        return None


def push_reading(device_id, data, overall_score):
    """Appends one row to the Google Sheet. Silently no-ops if not configured."""
    if not Config.SHEETS_SYNC_ENABLED:
        return False
    sheet = _get_sheet()
    if sheet is None:
        return False
    try:
        row = [
            data.get("timestamp", datetime.utcnow().isoformat()),
            device_id,
            data.get("temperature_c", ""),
            data.get("humidity_pct", ""),
            data.get("soil_moisture_pct", ""),
            data.get("ph", ""),
            data.get("water_level_cm", ""),
            "Yes" if data.get("motion_detected") else "No",
            overall_score if overall_score is not None else "",
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        logger.warning("Failed to push reading to Google Sheets: %s", e)
        return False
