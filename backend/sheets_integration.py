"""
AI Verdant — Google Sheets Bridge

Google Sheets acts as the persistent backup/source for sensor history.

SQLite is the fast local database used by the Flask API. Because Render's
free filesystem is not persistent, the application restores readings from
Google Sheets when it starts.

Each reading stores its crop_type so historical readings retain the crop
context that was active when the reading was recorded.
"""

import logging
from datetime import datetime

from config import Config

logger = logging.getLogger("ai_verdant.sheets")

_client = None
_spreadsheet = None
_sheet = None


# ===========================================================================
# GOOGLE SHEETS HEADER
# ===========================================================================

HEADER_ROW = [
    "Timestamp",
    "Device ID",
    "Crop",
    "Temperature (°C)",
    "Humidity (%)",
    "Soil Moisture (%)",
    "pH",
    "Water Level (cm)",
    "Motion Detected",
    "Overall Score",
]


# ===========================================================================
# GOOGLE CLIENT
# ===========================================================================

def _get_client():
    """
    Initialise and return the Google Sheets client.
    """

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
            "Google Sheets features are unavailable until configured.",
            Config.GOOGLE_SERVICE_ACCOUNT_FILE,
        )

        return None

    except Exception as e:

        logger.warning(
            "Could not initialise Google Sheets client: %s",
            e,
        )

        return None


# ===========================================================================
# OPEN MAIN SPREADSHEET
# ===========================================================================

def _get_spreadsheet():
    """
    Open the configured Google Spreadsheet.
    """

    global _spreadsheet

    if _spreadsheet is not None:
        return _spreadsheet

    client = _get_client()

    if client is None:
        return None

    try:

        if Config.GOOGLE_SHEET_ID:
            _spreadsheet = client.open_by_key(
                Config.GOOGLE_SHEET_ID
            )

        else:
            _spreadsheet = client.open(
                Config.GOOGLE_SHEET_NAME
            )

        return _spreadsheet

    except Exception as e:

        logger.warning(
            "Could not open Google Spreadsheet: %s",
            e,
        )

        return None


# ===========================================================================
# OPEN READINGS WORKSHEET
# ===========================================================================

def _get_sheet():
    """
    Open the Readings worksheet.

    If the worksheet does not exist, create it.

    If an older version of the project created the worksheet with the old
    9-column header, migrate the header to the new crop-aware 10-column
    format while preserving existing rows.
    """

    global _sheet

    if _sheet is not None:
        return _sheet

    spreadsheet = _get_spreadsheet()

    if spreadsheet is None:
        return None

    try:

        # -------------------------------------------------------------------
        # Find or create Readings worksheet.
        # -------------------------------------------------------------------

        try:

            worksheet = spreadsheet.worksheet(
                "Readings"
            )

        except Exception:

            worksheet = spreadsheet.add_worksheet(
                title="Readings",
                rows=2000,
                cols=len(HEADER_ROW),
            )

            worksheet.update(
                "A1",
                [HEADER_ROW],
            )

            _sheet = worksheet

            return _sheet

        # -------------------------------------------------------------------
        # Read current header.
        # -------------------------------------------------------------------

        first_row = worksheet.row_values(1)

        # Empty worksheet.
        if not first_row:

            worksheet.update(
                "A1",
                [HEADER_ROW],
            )

            _sheet = worksheet

            return _sheet

        # -------------------------------------------------------------------
        # Already using the new format.
        # -------------------------------------------------------------------

        if first_row[:len(HEADER_ROW)] == HEADER_ROW:

            _sheet = worksheet

            return _sheet

        # -------------------------------------------------------------------
        # Old format detection.
        #
        # Previous version:
        #
        # Timestamp
        # Device ID
        # Temperature
        # Humidity
        # Soil Moisture
        # pH
        # Water Level
        # Motion
        # Overall Score
        # -------------------------------------------------------------------

        old_header = [
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

        if first_row[:len(old_header)] == old_header:

            logger.info(
                "Detected legacy 9-column Readings header. "
                "Migrating to crop-aware 10-column format."
            )

            try:

                worksheet.insert_cols(
                    [[""] for _ in range(
                        max(worksheet.row_count, 1)
                    )],
                    col=3,
                )

                worksheet.update(
                    "A1",
                    [HEADER_ROW],
                )

                logger.info(
                    "Readings worksheet header migration complete. "
                    "Existing readings have blank Crop values and will be "
                    "handled during restoration."
                )

            except Exception as migration_error:

                logger.warning(
                    "Could not migrate legacy Readings header: %s",
                    migration_error,
                )

            _sheet = worksheet

            return _sheet

        # -------------------------------------------------------------------
        # Unknown header.
        #
        # Do not destroy data.
        # Do not use get_all_records() later because it requires unique
        # headers. Restoration reads cells by position instead.
        # -------------------------------------------------------------------

        logger.warning(
            "Readings worksheet has an unexpected header: %s",
            first_row,
        )

        _sheet = worksheet

        return _sheet

    except Exception as e:

        logger.warning(
            "Could not open Google Sheets Readings worksheet: %s",
            e,
        )

        return None


# ===========================================================================
# PUSH ONE READING TO GOOGLE SHEETS
# ===========================================================================

def push_reading(
    device_id,
    data,
    overall_score,
):
    """
    Append one sensor reading to the persistent Google Sheet.

    The crop is stored alongside the sensor values.

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

        crop_type = data.get(
            "crop_type"
        )

        if crop_type is None:
            crop_type = ""

        row = [

            # Timestamp
            data.get(
                "timestamp",
                datetime.utcnow().isoformat(),
            ),

            # Device
            device_id,

            # Crop
            crop_type,

            # Temperature
            data.get(
                "temperature_c",
                "",
            ),

            # Humidity
            data.get(
                "humidity_pct",
                "",
            ),

            # Soil moisture
            data.get(
                "soil_moisture_pct",
                "",
            ),

            # pH
            data.get(
                "ph",
                "",
            ),

            # Water level
            data.get(
                "water_level_cm",
                "",
            ),

            # Motion
            "Yes"
            if data.get("motion_detected")
            else "No",

            # Overall score
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


# ===========================================================================
# SAFE NUMBER CONVERSION
# ===========================================================================

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


# ===========================================================================
# MOTION VALUE CONVERSION
# ===========================================================================

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


# ===========================================================================
# SAFE CROP CONVERSION
# ===========================================================================

def _to_crop(value):
    """
    Convert a Google Sheets crop value into a clean string.

    Empty values become None.
    """

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return text


# ===========================================================================
# RESTORE READINGS FROM GOOGLE SHEETS
# ===========================================================================

def restore_readings_to_database(db):
    """
    Restore all readings stored in Google Sheets into SQLite.

    IMPORTANT:
        This function intentionally uses get_all_values() instead of
        get_all_records().

        gspread's get_all_records() requires the worksheet header row to
        contain unique column names. If Google Sheets has a duplicate or
        visually unusual header, get_all_records() throws an exception and
        prevents ALL readings from being restored.

        get_all_values() reads the raw cells directly, so we can safely
        process the intended A:J structure by column position.

    Google Sheets columns:

        A = Timestamp
        B = Device ID
        C = Crop
        D = Temperature (°C)
        E = Humidity (%)
        F = Soil Moisture (%)
        G = pH
        H = Water Level (cm)
        I = Motion Detected
        J = Overall Score

    Crop restoration priority:

        1. Crop stored on the individual Google Sheets reading.
        2. Existing crop stored on the SQLite device.
        3. Config.DEFAULT_CROP.

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

    # -----------------------------------------------------------------------
    # IMPORTANT:
    #
    # Use get_all_values(), NOT get_all_records().
    #
    # This avoids gspread's duplicate-header validation.
    # -----------------------------------------------------------------------

    try:

        values = sheet.get_all_values()

    except Exception as e:

        logger.warning(
            "Could not read readings from Google Sheets: %s",
            e,
        )

        return 0

    if not values:

        logger.info(
            "Google Sheets Readings worksheet is empty."
        )

        return 0

    if len(values) < 2:

        logger.info(
            "Google Sheets Readings worksheet contains only the header."
        )

        return 0

    # -----------------------------------------------------------------------
    # Header inspection.
    #
    # We log it for diagnostics but DO NOT reject the worksheet merely
    # because the headers are duplicated or slightly different.
    #
    # The actual data is read using fixed A:J positions.
    # -----------------------------------------------------------------------

    header = values[0]

    logger.info(
        "Google Sheets Readings header detected: %s",
        header,
    )

    # -----------------------------------------------------------------------
    # Process every data row.
    # -----------------------------------------------------------------------

    restored_count = 0

    data_rows = values[1:]

    logger.info(
        "Found %s readings in Google Sheets. "
        "Starting SQLite restoration.",
        len(data_rows),
    )

    for row_number, raw_row in enumerate(
        data_rows,
        start=2,
    ):

        try:

            # ---------------------------------------------------------------
            # Guarantee at least 10 columns.
            #
            # This protects against rows that have fewer cells than A:J.
            # ---------------------------------------------------------------

            row = list(raw_row)

            if len(row) < 10:

                row.extend(
                    [""] * (10 - len(row))
                )

            # Only the intended A:J columns are used.
            row = row[:10]

            # ---------------------------------------------------------------
            # A — Timestamp
            # ---------------------------------------------------------------

            timestamp = str(
                row[0]
            ).strip()

            # ---------------------------------------------------------------
            # B — Device ID
            # ---------------------------------------------------------------

            device_id = str(
                row[1]
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

            # ---------------------------------------------------------------
            # C — Crop
            # ---------------------------------------------------------------

            crop_type = _to_crop(
                row[2]
            )

            # ---------------------------------------------------------------
            # D:J — Sensor data
            # ---------------------------------------------------------------

            data = {

                "timestamp": timestamp,

                "crop_type": crop_type,

                "temperature_c": _to_float(
                    row[3]
                ),

                "humidity_pct": _to_float(
                    row[4]
                ),

                "soil_moisture_pct": _to_float(
                    row[5]
                ),

                "ph": _to_float(
                    row[6]
                ),

                "water_level_cm": _to_float(
                    row[7]
                ),

                "motion_detected": _to_motion(
                    row[8]
                ),
            }

            # ---------------------------------------------------------------
            # J — Overall Score
            # ---------------------------------------------------------------

            overall_score = _to_float(
                row[9]
            )

            # ---------------------------------------------------------------
            # Look for an existing device.
            # ---------------------------------------------------------------

            existing_device = db.get_device(
                device_id
            )

            # ---------------------------------------------------------------
            # If the Google Sheet row has no crop, preserve the existing
            # device crop where possible.
            # ---------------------------------------------------------------

            if not crop_type:

                if existing_device:

                    crop_type = existing_device.get(
                        "crop_type"
                    )

                if not crop_type:

                    crop_type = Config.DEFAULT_CROP

                data["crop_type"] = crop_type

            # ---------------------------------------------------------------
            # Make sure the device exists.
            #
            # Pass crop_type so the device itself also retains crop context.
            # ---------------------------------------------------------------

            db.upsert_device(
                device_id=device_id,

                name=(
                    existing_device.get("name")
                    if existing_device
                    else device_id
                ),

                farm_name=(
                    existing_device.get("farm_name")
                    if existing_device
                    else None
                ),

                location=(
                    existing_device.get("location")
                    if existing_device
                    else None
                ),

                crop_type=crop_type,
            )

            # ---------------------------------------------------------------
            # Prevent duplicate restoration.
            # ---------------------------------------------------------------

            before = db.reading_exists(
                device_id,
                timestamp,
            )

            # ---------------------------------------------------------------
            # Insert the reading.
            # ---------------------------------------------------------------

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


# ===========================================================================
# CROP REQUIREMENTS
# ===========================================================================

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

        worksheet = spreadsheet.worksheet(
            "Crops"
        )

        rows = worksheet.get_all_records()

        requested_crop_name = str(
            crop_name
        ).strip().lower()

        for row in rows:

            sheet_crop_name = str(
                row.get(
                    "Crop Name",
                    "",
                )
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