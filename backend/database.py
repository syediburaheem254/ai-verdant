"""
AI Verdant — Local Database Layer

SQLite is used as the fast local query/cache database.

IMPORTANT:
Render's free filesystem is not persistent. Therefore this database
can disappear when the service restarts.

Google Sheets is the persistent backup/source for sensor history.
On application startup, app.py restores readings from Google Sheets
into this SQLite database.

This database stores crop_type on each reading so that historical
sensor readings retain the crop context that was active when they
were recorded.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from contextlib import contextmanager

from config import Config


# ===========================================================================
# DATABASE LOCATION
# ===========================================================================

DATABASE_DIR = os.path.dirname(Config.DATABASE_PATH)

if DATABASE_DIR:
    os.makedirs(DATABASE_DIR, exist_ok=True)


# ===========================================================================
# DATABASE SCHEMA
# ===========================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    farm_name       TEXT,
    location        TEXT,
    crop_type       TEXT,
    created_at      TEXT NOT NULL,
    last_seen       TEXT
);

CREATE TABLE IF NOT EXISTS readings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    crop_type           TEXT,
    temperature_c       REAL,
    humidity_pct        REAL,
    soil_moisture_pct   REAL,
    ph                  REAL,
    water_level_cm      REAL,
    motion_detected     INTEGER,
    overall_score       REAL,
    FOREIGN KEY (device_id) REFERENCES devices (device_id)
);

CREATE INDEX IF NOT EXISTS idx_readings_device_time
    ON readings (device_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_readings_device_crop
    ON readings (device_id, crop_type);

CREATE TABLE IF NOT EXISTS recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    category        TEXT NOT NULL,
    severity        TEXT NOT NULL,
    message         TEXT NOT NULL,
    strategy        TEXT,
    FOREIGN KEY (device_id) REFERENCES devices (device_id)
);
"""


# ===========================================================================
# DATABASE CONNECTION
# ===========================================================================

@contextmanager
def get_db():
    """
    Open a SQLite connection with safe transaction handling.
    """

    conn = sqlite3.connect(Config.DATABASE_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ===========================================================================
# DATABASE MIGRATIONS
# ===========================================================================

def _column_exists(conn, table_name, column_name):
    """
    Check whether a column already exists in a SQLite table.
    """

    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return any(
        row["name"] == column_name
        for row in rows
    )


def _run_migrations(conn):
    """
    Apply small, backwards-compatible database migrations.

    This is important because CREATE TABLE IF NOT EXISTS does NOT modify
    an already-existing table.

    Therefore, older databases that were created before crop_type was
    introduced need an explicit ALTER TABLE operation.
    """

    # -----------------------------------------------------------------------
    # Add crop_type to readings if the database is from an older version.
    # -----------------------------------------------------------------------

    if not _column_exists(
        conn,
        "readings",
        "crop_type",
    ):
        conn.execute(
            """
            ALTER TABLE readings
            ADD COLUMN crop_type TEXT
            """
        )

    # -----------------------------------------------------------------------
    # Make sure the crop index exists.
    # -----------------------------------------------------------------------

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_readings_device_crop
        ON readings (device_id, crop_type)
        """
    )


# ===========================================================================
# INITIALISE DATABASE
# ===========================================================================

def init_db():
    """
    Create all database tables and apply migrations.

    The database may be empty after a Render restart.
    Google Sheets restoration is handled separately by app.py.
    """

    with get_db() as conn:

        # Create new installations.
        conn.executescript(SCHEMA)

        # Upgrade older installations safely.
        _run_migrations(conn)

        # -------------------------------------------------------------------
        # Seed demo device.
        #
        # INSERT OR IGNORE means an existing device is never overwritten.
        # -------------------------------------------------------------------

        conn.execute(
            """
            INSERT OR IGNORE INTO devices
            (
                device_id,
                name,
                farm_name,
                location,
                crop_type,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "device-001",
                "Field A Node",
                "Green Valley Farm",
                "North Plot",
                Config.DEFAULT_CROP,
                datetime.utcnow().isoformat(),
            ),
        )


# ===========================================================================
# DEVICE MANAGEMENT
# ===========================================================================

def upsert_device(
    device_id,
    name=None,
    farm_name=None,
    location=None,
    crop_type=None,
):
    """
    Insert a device if it doesn't exist.

    If it already exists, update only the values supplied by the caller.

    crop_type is preserved when the caller does not provide a new value.
    """

    with get_db() as conn:

        existing = conn.execute(
            """
            SELECT *
            FROM devices
            WHERE device_id = ?
            """,
            (device_id,),
        ).fetchone()

        now = datetime.utcnow().isoformat()

        if existing:

            conn.execute(
                """
                UPDATE devices

                SET name = COALESCE(?, name),
                    farm_name = COALESCE(?, farm_name),
                    location = COALESCE(?, location),
                    crop_type = COALESCE(?, crop_type),
                    last_seen = ?

                WHERE device_id = ?
                """,
                (
                    name,
                    farm_name,
                    location,
                    crop_type,
                    now,
                    device_id,
                ),
            )

        else:

            conn.execute(
                """
                INSERT INTO devices
                (
                    device_id,
                    name,
                    farm_name,
                    location,
                    crop_type,
                    created_at,
                    last_seen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    name or device_id,
                    farm_name,
                    location,
                    crop_type or Config.DEFAULT_CROP,
                    now,
                    now,
                ),
            )


# ===========================================================================
# GET DEVICE
# ===========================================================================

def get_device(device_id):
    """
    Return one device as a dictionary.

    Returns None when the device does not exist.
    """

    with get_db() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM devices
            WHERE device_id = ?
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()

        return dict(row) if row else None


# ===========================================================================
# INSERT SENSOR READING
# ===========================================================================

def insert_reading(
    device_id,
    data,
    overall_score,
):
    """
    Insert a new sensor reading.

    The crop_type is taken from data["crop_type"] when available.

    If the reading does not explicitly contain a crop, the current
    crop assigned to the device is used as a fallback.

    Duplicate device + timestamp combinations are ignored.
    """

    timestamp = data.get(
        "timestamp",
        datetime.utcnow().isoformat(),
    )

    # -----------------------------------------------------------------------
    # Determine crop for this reading.
    #
    # Priority:
    #
    # 1. Crop explicitly attached to the reading.
    # 2. Current crop stored on the device.
    # 3. Config.DEFAULT_CROP.
    # -----------------------------------------------------------------------

    crop_type = data.get("crop_type")

    if crop_type is not None:
        crop_type = str(crop_type).strip()

        if not crop_type:
            crop_type = None

    if crop_type is None:

        with get_db() as conn:

            device_row = conn.execute(
                """
                SELECT crop_type
                FROM devices
                WHERE device_id = ?
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()

            if device_row:
                crop_type = device_row["crop_type"]

    if not crop_type:
        crop_type = Config.DEFAULT_CROP

    with get_db() as conn:

        # -------------------------------------------------------------------
        # Prevent duplicate restoration.
        # -------------------------------------------------------------------

        existing = conn.execute(
            """
            SELECT id
            FROM readings
            WHERE device_id = ?
              AND timestamp = ?
            LIMIT 1
            """,
            (
                device_id,
                timestamp,
            ),
        ).fetchone()

        if existing:
            return existing["id"]

        # -------------------------------------------------------------------
        # Insert reading.
        # -------------------------------------------------------------------

        cursor = conn.execute(
            """
            INSERT INTO readings
            (
                device_id,
                timestamp,
                crop_type,
                temperature_c,
                humidity_pct,
                soil_moisture_pct,
                ph,
                water_level_cm,
                motion_detected,
                overall_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                timestamp,
                crop_type,
                data.get("temperature_c"),
                data.get("humidity_pct"),
                data.get("soil_moisture_pct"),
                data.get("ph"),
                data.get("water_level_cm"),
                int(bool(data.get("motion_detected", False))),
                overall_score,
            ),
        )

        return cursor.lastrowid


# ===========================================================================
# INSERT RECOMMENDATION
# ===========================================================================

def insert_recommendation(
    device_id,
    category,
    severity,
    message,
    strategy="",
):
    """
    Store one generated recommendation.
    """

    with get_db() as conn:

        conn.execute(
            """
            INSERT INTO recommendations
            (
                device_id,
                timestamp,
                category,
                severity,
                message,
                strategy
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                datetime.utcnow().isoformat(),
                category,
                severity,
                message,
                strategy,
            ),
        )


# ===========================================================================
# GET LATEST READING
# ===========================================================================

def get_latest_reading(device_id):
    """
    Return the most recent reading for a device.
    """

    with get_db() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM readings

            WHERE device_id = ?

            ORDER BY timestamp DESC

            LIMIT 1
            """,
            (device_id,),
        ).fetchone()

        return dict(row) if row else None


# ===========================================================================
# GET HISTORY
# ===========================================================================

def get_history(
    device_id,
    hours=24,
):
    """
    Return readings from the requested number of previous hours.
    """

    try:
        hours = int(hours)

    except (TypeError, ValueError):
        hours = 24

    if hours < 1:
        hours = 1

    since = (
        datetime.utcnow()
        - timedelta(hours=hours)
    ).isoformat()

    with get_db() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM readings

            WHERE device_id = ?
              AND timestamp >= ?

            ORDER BY timestamp ASC
            """,
            (
                device_id,
                since,
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


# ===========================================================================
# GET ALL READINGS
# ===========================================================================

def get_all_readings(
    device_id=None,
):
    """
    Return all readings.

    If device_id is supplied, only that device's readings are returned.
    """

    with get_db() as conn:

        if device_id:

            rows = conn.execute(
                """
                SELECT *
                FROM readings

                WHERE device_id = ?

                ORDER BY timestamp ASC
                """,
                (device_id,),
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT *
                FROM readings

                ORDER BY timestamp ASC
                """
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


# ===========================================================================
# GET READINGS FOR A SPECIFIC CROP
# ===========================================================================

def get_readings_by_crop(
    device_id,
    crop_type,
):
    """
    Return readings belonging to a specific crop.

    This is useful for historical crop-aware analysis and trends.
    """

    with get_db() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM readings

            WHERE device_id = ?
              AND crop_type = ?

            ORDER BY timestamp ASC
            """,
            (
                device_id,
                crop_type,
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


# ===========================================================================
# GET RECOMMENDATIONS
# ===========================================================================

def get_recommendations(
    device_id,
    limit=20,
):
    """
    Return recent recommendations for a device.
    """

    with get_db() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM recommendations

            WHERE device_id = ?

            ORDER BY timestamp DESC

            LIMIT ?
            """,
            (
                device_id,
                int(limit),
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


# ===========================================================================
# LIST DEVICES
# ===========================================================================

def list_devices():
    """
    Return all registered devices.
    """

    with get_db() as conn:

        rows = conn.execute(
            """
            SELECT *
            FROM devices

            ORDER BY created_at ASC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


# ===========================================================================
# CHECK WHETHER A READING EXISTS
# ===========================================================================

def reading_exists(
    device_id,
    timestamp,
):
    """
    Return True when a device/timestamp reading already exists.
    """

    with get_db() as conn:

        row = conn.execute(
            """
            SELECT id
            FROM readings

            WHERE device_id = ?
              AND timestamp = ?

            LIMIT 1
            """,
            (
                device_id,
                timestamp,
            ),
        ).fetchone()

        return row is not None