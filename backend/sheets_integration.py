"""
AI Verdant — Google Sheets Bridge

Mirrors sensor readings into Google Sheets so the raw data remains
persistent even when the Render free service restarts.

Google Sheets is also used as the persistent backup/source for sensor
history. On application startup, app.py can restore those readings
into the local SQLite database.
"""

import logging
from datetime import datetime

from config import Config

logger = logging.getLogger("ai_verdant.sheets")

_client = None
_sheet = None


# ---------------------------------------------------------------------------
# GOOGLE SHEETS HEADER
# ---------------------------------------------------------------------------

HEADER_ROW = [
    "Timestamp",
    "Device ID",
    "Temperature (°C)",
    "Humidity (%)",
    "Soil Moisture (%)",
    "pH",
    "Water Level (cm)",
    "Motion Detected",
    "Overall Score",
]


# ---------------------------------------------------------------------------
# GOOGLE CLIENT
# ---------------------------------------------------------------------------

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
            Config.GOOGLE_SERVICE_ACCOUNT_FILE,
            scopes=scopes,
        )

        _client = gspread.authorize(creds)

        return _client

    except FileNotFoundError:
        logger.warning(
            "Google service account file not found at %s. "
            "Google Sheets features are unavailable until it is configured.",
            Config.GOOGLE_SERVICE_ACCOUNT_FILE,
        )
        return None

    except Exception as e:
        logger.warning(
            "Could not initialise Google Sheets client: %s",
            e,
        )
        return None


# ---------------------------------------------------------------------------
# OPEN MAIN SPREADSHEET
# ---------------------------------------------------------------------------

def _get_spreadsheet():
    client = _get_client()

    if client is None:
        return None

    try:
        if Config.GOOGLE_SHEET_ID:
            return client.open_by_key(Config.GOOGLE_SHEET_ID)

        return client.open(Config.GOOGLE_SHEET_NAME)

    except Exception as e:
        logger.warning(
            "Could not open Google Spreadsheet: %s",
            e,
        )
        return None


# ---------------------------------------------------------------------------
# OPEN READINGS WORKSHEET
# ---------------------------------------------------------------------------

def _get_sheet():
    global _sheet

    if _sheet is not None:
        return _sheet

    spreadsheet = _get_spreadsheet()

    if spreadsheet is None:
        return None

    try:
        try:
            worksheet = spreadsheet.worksheet("Readings")

        except Exception:
            worksheet = spreadsheet.add_worksheet(
                title="Readings",
                rows=2000,
                cols=len(HEADER_ROW),
            )

            worksheet.append_row(
                HEADER_ROW,
                value_input_option="USER_ENTERED",
            )

        # Make sure the first row contains the expected headers.
        first_row = worksheet.row_values(1)

        if first_row != HEADER_ROW:
            worksheet.update(
                "A1",
                [HEADER_ROW],
            )

        _sheet = worksheet

        return _sheet

    except Exception as e:
        logger.warning(
            "Could not open Google Sheets Readings worksheet: %s",
            e,
        )
        return None


# ---------------------------------------------------------------------------
# PUSH ONE READING TO GOOGLE SHEETS
# ---------------------------------------------------------------------------

def push_reading(device_id, data, overall_score):
    """
    Append one sensor reading to the persistent Google Sheet.

    Returns:
        True  -> successfully synced
        False -> sync failed or is disabled
    """

    if not Config.SHEETS_SYNC_ENABLED:
        return False

    sheet = _get_sheet()

    if sheet is None:
        return False

    try:
        row = [
            data.get(
                "timestamp",
                datetime.utcnow().isoformat(),
            ),

            device_id,

            data.get(
                "temperature_c",
                "",
            ),

            data.get(
                "humidity_pct",
                "",
            ),

            data.get(
                "soil_moisture_pct",
                "",
            ),

            data.get(
                "ph",
                "",
            ),

            data.get(
                "water_level_cm",
                "",
            ),

            "Yes"
            if data.get("motion_detected")
            else "No",

            overall_score
            if overall_score is not None
            else "",
        ]

        sheet.append_row(
            row,
            value_input_option="USER_ENTERED",
        )

        return True

    except Exception as e:
        logger.warning(
            "Failed to push reading to Google Sheets: %s",
            e,
        )
        return False


# ---------------------------------------------------------------------------
# SAFE NUMBER CONVERSION
# ---------------------------------------------------------------------------

def _to_float(value):
    """
    Convert a Google Sheets cell value to float.

    Empty or invalid values become None.
    """

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if not text:
        return None

    try:
        return float(text)

    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# MOTION VALUE CONVERSION
# ---------------------------------------------------------------------------

def _to_motion(value):
    """
    Convert Google Sheets motion values such as:

        Yes / No
        True / False
        1 / 0

    into an integer 1 or 0.
    """

    if value is None:
        return 0

    if isinstance(value, bool):
        return 1 if value else 0

    text = str(value).strip().lower()

    if text in (
        "yes",
        "true",
        "1",
        "on",
        "detected",
    ):
        return 1

    return 0


# ---------------------------------------------------------------------------
# RESTORE READINGS FROM GOOGLE SHEETS
# ---------------------------------------------------------------------------

def restore_readings_to_database(db):
    """
    Restore all readings stored in Google Sheets into SQLite.

    This is intended to run when the Flask application starts.

    Google Sheets:
        persistent storage

    SQLite:
        fast local cache/query database

    Existing readings are not duplicated because database.insert_reading()
    checks device_id + timestamp before inserting.

    Returns:
        Number of newly restored readings.
    """

    if not Config.SHEETS_SYNC_ENABLED:
        logger.info(
            "Google Sheets sync is disabled. "
            "Skipping database restoration."
        )
        return 0

    sheet = _get_sheet()

    if sheet is None:
        logger.warning(
            "Could not access Google Sheets. "
            "Skipping database restoration."
        )
        return 0

    try:
        rows = sheet.get_all_records()

    except Exception as e:
        logger.warning(
            "Could not read readings from Google Sheets: %s",
            e,
        )
        return 0

    if not rows:
        logger.info(
            "Google Sheets Readings worksheet is empty."
        )
        return 0

    restored_count = 0

    logger.info(
        "Found %s readings in Google Sheets. "
        "Starting SQLite restoration.",
        len(rows),
    )

    for row_number, row in enumerate(rows, start=2):

        try:
            device_id = str(
                row.get("Device ID", "")
            ).strip()

            timestamp = str(
                row.get("Timestamp", "")
            ).strip()

            if not device_id:
                logger.warning(
                    "Skipping Google Sheets row %s: "
                    "missing Device ID.",
                    row_number,
                )
                continue

            if not timestamp:
                logger.warning(
                    "Skipping Google Sheets row %s: "
                    "missing Timestamp.",
                    row_number,
                )
                continue

            data = {
                "timestamp": timestamp,

                "temperature_c": _to_float(
                    row.get("Temperature (°C)")
                ),

                "humidity_pct": _to_float(
                    row.get("Humidity (%)")
                ),

                "soil_moisture_pct": _to_float(
                    row.get("Soil Moisture (%)")
                ),

                "ph": _to_float(
                    row.get("pH")
                ),

                "water_level_cm": _to_float(
                    row.get("Water Level (cm)")
                ),

                "motion_detected": _to_motion(
                    row.get("Motion Detected")
                ),
            }

            overall_score = _to_float(
                row.get("Overall Score")
            )

            # Make sure the device exists before inserting the reading.
            db.upsert_device(
                device_id=device_id,
                name=device_id,
            )

            # insert_reading() already prevents duplicate
            # device_id + timestamp combinations.
            before = db.reading_exists(
                device_id,
                timestamp,
            )

            db.insert_reading(
                device_id=device_id,
                data=data,
                overall_score=overall_score,
            )

            if not before:
                restored_count += 1

        except Exception as e:
            logger.warning(
                "Failed to restore Google Sheets row %s: %s",
                row_number,
                e,
            )

    logger.info(
        "Google Sheets restoration complete. "
        "Restored %s new readings.",
        restored_count,
    )

    return restored_count


# ---------------------------------------------------------------------------
# CROP REQUIREMENTS
# ---------------------------------------------------------------------------

def get_crop_requirements(crop_name):
    """
    Read one crop's requirements from the Crops worksheet.
    """

    client = _get_client()

    if client is None:
        return None

    try:
        spreadsheet = _get_spreadsheet()

        if spreadsheet is None:
            return None

        worksheet = spreadsheet.worksheet("Crops")

        rows = worksheet.get_all_records()

        for row in rows:

            sheet_crop_name = str(
                row.get("Crop Name", "")
            ).strip().lower()

            requested_crop_name = str(
                crop_name
            ).strip().lower()

            if sheet_crop_name == requested_crop_name:
                return row

        logger.warning(
            "Crop '%s' was not found in the Crops sheet.",
            crop_name,
        )

        return None

    except Exception as e:
        logger.warning(
            "Could not read crop requirements: %s",
            e,
        )
        return None