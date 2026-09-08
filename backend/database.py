"""
AI Verdant — Local database layer (SQLite)

Why a local DB *and* Google Sheets?
- SQLite is the fast, reliable source of truth the app queries for
  charts, scoring, and recommendations.
- Google Sheets is the human-friendly mirror the user asked for —
  easy to open on a phone, share with a family member, or export.

Every ingested reading is written to both.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from config import Config

os.makedirs(os.path.dirname(Config.DATABASE_PATH), exist_ok=True)


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
    water_level_cm      REAL,   -- from ultrasonic sensor
    motion_detected     INTEGER, -- 0/1
    overall_score       REAL,
    FOREIGN KEY (device_id) REFERENCES devices (device_id)
);

CREATE INDEX IF NOT EXISTS idx_readings_device_time
    ON readings (device_id, timestamp);

CREATE TABLE IF NOT EXISTS recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    category        TEXT NOT NULL,   -- e.g. "irrigation", "ph", "pest_risk"
    severity        TEXT NOT NULL,   -- "info" | "watch" | "action" | "urgent"
    message         TEXT NOT NULL,
    strategy        TEXT,
    FOREIGN KEY (device_id) REFERENCES devices (device_id)
);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # Seed one demo device so the app has something to show on first run
        conn.execute(
            """INSERT OR IGNORE INTO devices
               (device_id, name, farm_name, location, crop_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("device-001", "Field A Node", "Green Valley Farm", "North Plot",
             "Tomato", datetime.utcnow().isoformat()),
        )


def upsert_device(device_id, name=None, farm_name=None, location=None, crop_type=None):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()

        now = datetime.utcnow().isoformat()

        if existing:
            conn.execute(
                """UPDATE devices
                   SET name = COALESCE(?, name),
                       farm_name = COALESCE(?, farm_name),
                       location = COALESCE(?, location),
                       crop_type = COALESCE(?, crop_type),
                       last_seen = ?
                   WHERE device_id = ?""",
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
                """INSERT INTO devices
                   (device_id, name, farm_name, location, crop_type, created_at, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    device_id,
                    name or device_id,
                    farm_name,
                    location,
                    crop_type,
                    now,
                    now,
                ),
            )


def insert_reading(device_id, data, overall_score):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO readings
               (device_id, timestamp, temperature_c, humidity_pct, soil_moisture_pct,
                ph, water_level_cm, motion_detected, overall_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id,
                data.get("timestamp", datetime.utcnow().isoformat()),
                data.get("temperature_c"),
                data.get("humidity_pct"),
                data.get("soil_moisture_pct"),
                data.get("ph"),
                data.get("water_level_cm"),
                int(bool(data.get("motion_detected", False))),
                overall_score,
            ),
        )


def insert_recommendation(device_id, category, severity, message, strategy=""):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO recommendations
               (device_id, timestamp, category, severity, message, strategy)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (device_id, datetime.utcnow().isoformat(), category, severity, message, strategy),
        )


def get_latest_reading(device_id):
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM readings WHERE device_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (device_id,),
        ).fetchone()
        return dict(row) if row else None


def get_history(device_id, hours=24):
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM readings WHERE device_id = ? AND timestamp >= ?
               ORDER BY timestamp ASC""",
            (device_id, since),
        ).fetchall()
        return [dict(r) for r in rows]


def get_recommendations(device_id, limit=20):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM recommendations WHERE device_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (device_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_devices():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]
