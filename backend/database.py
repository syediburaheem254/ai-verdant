"""
AI Verdant — Local Database Layer

SQLite is used as the fast local query/cache database.

IMPORTANT:
Render's free filesystem is not persistent. Therefore this database
can disappear when the service restarts.

Google Sheets is the persistent backup/source for sensor history.
On application startup, app.py restores readings from Google Sheets
into this SQLite database.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from config import Config


# ---------------------------------------------------------------------------
# DATABASE LOCATION
# ---------------------------------------------------------------------------

DATABASE_DIR = os.path.dirname(Config.DATABASE_PATH)

if DATABASE_DIR:
    os.makedirs(DATABASE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# DATABASE SCHEMA
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
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


# ---------------------------------------------------------------------------
# INITIALISE DATABASE
# ---------------------------------------------------------------------------

def init_db():
    """
    Create all database tables.

    The database may be empty after a Render restart.
    Google Sheets restoration is handled separately by app.py.
    """

    with get_db() as conn:

        conn.executescript(SCHEMA)

        # Seed demo device.
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


# ---------------------------------------------------------------------------
# DEVICE MANAGEMENT
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# INSERT SENSOR READING
# ---------------------------------------------------------------------------

def insert_reading(device_id, data, overall_score):
    """
    Insert a new sensor reading.

    Duplicate timestamp + device combinations are ignored. This is
    important when restoring Google Sheets data after a restart.
    """

    timestamp = data.get(
        "timestamp",
        datetime.utcnow().isoformat(),
    )

    with get_db() as conn:

        # Prevent duplicate restoration.
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

        cursor = conn.execute(
            """
            INSERT INTO readings
            (
                device_id,
                timestamp,
                temperature_c,
                humidity_pct,
                soil_moisture_pct,
                ph,
                water_level_cm,
                motion_detected,
                overall_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                timestamp,
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


# ---------------------------------------------------------------------------
# INSERT RECOMMENDATION
# ---------------------------------------------------------------------------

def insert_recommendation(
    device_id,
    category,
    severity,
    message,
    strategy="",
):
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


# ---------------------------------------------------------------------------
# GET LATEST READING
# ---------------------------------------------------------------------------

def get_latest_reading(device_id):

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


# ---------------------------------------------------------------------------
# GET HISTORY
# ---------------------------------------------------------------------------

def get_history(device_id, hours=24):

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


# ---------------------------------------------------------------------------
# GET ALL READINGS
# ---------------------------------------------------------------------------

def get_all_readings(device_id=None):

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


# ---------------------------------------------------------------------------
# GET RECOMMENDATIONS
# ---------------------------------------------------------------------------

def get_recommendations(device_id, limit=20):

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


# ---------------------------------------------------------------------------
# LIST DEVICES
# ---------------------------------------------------------------------------

def list_devices():

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


# ---------------------------------------------------------------------------
# CHECK WHETHER A READING EXISTS
# ---------------------------------------------------------------------------

def reading_exists(device_id, timestamp):

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