"""
AI Verdant — Backend Configuration
Centralised settings for the Flask API, the local database, and the
Google Sheets bridge. Copy `.env.example` to `.env` and fill in real
values before running the server.
"""

import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # --- General ---------------------------------------------------------
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
    DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))

    # --- API auth for the hardware device --------------------------------
    # The ESP32/Arduino sends this key in the "X-Device-Key" header so
    # random people can't post fake readings to your farm.
    DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "farm-secret-key-change-me")

    # --- Local database (SQLite) -----------------------------------------
    DATABASE_PATH = os.path.join(BASE_DIR, "data", "ai_verdant.db")

    # --- Google Sheets bridge ---------------------------------------------
    GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        os.path.join(BASE_DIR, "service_account.json"),
    )
    GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "AI Farming - Sensor Log")
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")  # optional, faster than name lookup
    SHEETS_SYNC_ENABLED = os.getenv("SHEETS_SYNC_ENABLED", "true").lower() == "true"

    # --- Ideal ranges used by the scoring / recommendation engine --------
    # Tweak these per crop. Defaults below are safe general-purpose values.
    IDEAL_RANGES = {
        "temperature_c": (18, 30),
        "humidity_pct": (40, 70),
        "soil_moisture_pct": (35, 65),
        "ph": (6.0, 7.0),
        "water_level_cm": (5, 100),  # from ultrasonic sensor (tank/canopy distance use-case)
    }

    # --- QR / device portal -------------------------------------------------
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")
