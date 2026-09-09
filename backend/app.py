"""
AI Verdant — Backend API

Endpoints
---------
POST /api/ingest
GET  /api/devices
GET  /api/devices/<id>/latest
GET  /api/devices/<id>/history?hours=24
GET  /api/devices/<id>/recommendations
GET  /api/devices/<id>/strategy
GET  /portal/<id>
GET  /healthz
GET  /api/test-crop/<crop_name>
"""

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime
import logging

from config import Config
import database as db
import analysis
import sheets_integration as sheets


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("ai_verdant")


# ---------------------------------------------------------------------------
# FLASK APP
# ---------------------------------------------------------------------------

app = Flask(__name__)

app.config.from_object(Config)

CORS(app)


# ---------------------------------------------------------------------------
# DATABASE INITIALIZATION + GOOGLE SHEETS RESTORATION
# ---------------------------------------------------------------------------

db.init_db()

try:

    restored_count = sheets.restore_readings_to_database(db)

    logger.info(
        "Startup database restoration finished: %s readings restored.",
        restored_count,
    )

except Exception as e:

    logger.exception(
        "Startup database restoration failed: %s",
        e,
    )


# ---------------------------------------------------------------------------
# Helper: determine crop and analysis ranges
# ---------------------------------------------------------------------------

def get_crop_context(device_id, crop_name=None):
    """
    Determine which crop is being monitored and load its requirements.

    Priority:
        1. Explicit crop supplied by caller
        2. Crop stored in device registry
        3. Config.DEFAULT_CROP

    Returns:
        crop_name, crop_requirements, ranges
    """

    selected_crop = crop_name

    # ---------------------------------------------------------
    # 1. Try device registry if no crop was explicitly supplied
    # ---------------------------------------------------------

    if not selected_crop:

        try:

            device = db.get_device(device_id)

            if device:

                selected_crop = device.get("crop_type")

        except Exception as e:

            logger.warning(
                "Could not determine crop from device registry: %s",
                e,
            )

    # ---------------------------------------------------------
    # 2. Final fallback
    # ---------------------------------------------------------

    selected_crop = (
        selected_crop
        or Config.DEFAULT_CROP
    )

    # ---------------------------------------------------------
    # 3. Load crop requirements from Google Sheets
    # ---------------------------------------------------------

    crop_requirements = sheets.get_crop_requirements(
        selected_crop
    )

    # ---------------------------------------------------------
    # 4. Convert requirements to analysis ranges
    # ---------------------------------------------------------

    if crop_requirements:

        ranges = analysis.ranges_from_crop_requirements(
            crop_requirements
        )

    else:

        logger.warning(
            "No requirements found for crop '%s'. "
            "Using default analysis ranges.",
            selected_crop,
        )

        ranges = analysis.RANGES

    return (
        selected_crop,
        crop_requirements,
        ranges,
    )


# ---------------------------------------------------------------------------
# Ingest — called by ESP32 / Arduino
# ---------------------------------------------------------------------------

@app.route("/api/ingest", methods=["POST"])
def ingest():

    # ---------------------------------------------------------
    # 1. Authenticate device
    # ---------------------------------------------------------

    key = request.headers.get("X-Device-Key")

    if key != Config.DEVICE_API_KEY:

        return jsonify({
            "error": "unauthorized"
        }), 401

    # ---------------------------------------------------------
    # 2. Read JSON payload
    # ---------------------------------------------------------

    payload = request.get_json(
        silent=True
    )

    if not payload:

        return jsonify({
            "error": "expected JSON body"
        }), 400

    # ---------------------------------------------------------
    # 3. Validate device ID
    # ---------------------------------------------------------

    device_id = payload.get(
        "device_id"
    )

    if not device_id:

        return jsonify({
            "error": "device_id is required"
        }), 400

    # ---------------------------------------------------------
    # 4. Determine crop from this reading
    # ---------------------------------------------------------

    crop_name = (
        payload.get("crop_type")
        or Config.DEFAULT_CROP
    )

    # ---------------------------------------------------------
    # 5. Build sensor data
    # ---------------------------------------------------------

    data = {

        "timestamp": payload.get(
            "timestamp",
            datetime.utcnow().isoformat(),
        ),

        "crop_type": crop_name,

        "temperature_c": payload.get(
            "temperature_c"
        ),

        "humidity_pct": payload.get(
            "humidity_pct"
        ),

        "soil_moisture_pct": payload.get(
            "soil_moisture_pct"
        ),

        "ph": payload.get(
            "ph"
        ),

        "water_level_cm": payload.get(
            "water_level_cm"
        ),

        "motion_detected": payload.get(
            "motion_detected",
            False,
        ),
    }

    # ---------------------------------------------------------
    # 6. Register / update device
    # ---------------------------------------------------------

    db.upsert_device(

        device_id,

        name=payload.get(
            "device_name"
        ),

        farm_name=payload.get(
            "farm_name"
        ),

        location=payload.get(
            "location"
        ),

        crop_type=crop_name,

    )

    # ---------------------------------------------------------
    # 7. Determine crop-specific requirements
    # ---------------------------------------------------------

    (
        crop_name,
        crop_requirements,
        ranges,
    ) = get_crop_context(

        device_id,

        crop_name,

    )

    # Keep the resolved crop inside the reading data.
    data["crop_type"] = crop_name

    # ---------------------------------------------------------
    # 8. Analyze using crop-specific ranges
    # ---------------------------------------------------------

    scores, overall = analysis.score_reading(

        data,

        ranges,

    )

    # ---------------------------------------------------------
    # 9. Store reading in SQLite
    # ---------------------------------------------------------

    db.insert_reading(

        device_id,

        data,

        overall,

    )

    # ---------------------------------------------------------
    # 10. Generate crop-specific recommendations
    # ---------------------------------------------------------

    recs = analysis.generate_recommendations(

        data,

        scores,

        ranges=ranges,

    )

    # ---------------------------------------------------------
    # 11. Store recommendations
    # ---------------------------------------------------------

    for r in recs:

        db.insert_recommendation(

            device_id,

            r["category"],

            r["severity"],

            r["message"],

            r["strategy"],

        )

    # ---------------------------------------------------------
    # 12. Sync reading to Google Sheets
    # ---------------------------------------------------------

    sheets_ok = sheets.push_reading(

        device_id,

        data,

        overall,

    )

    # ---------------------------------------------------------
    # 13. Return result
    # ---------------------------------------------------------

    return jsonify({

        "status": "ok",

        "device_id": device_id,

        "crop": crop_name,

        "overall_score": overall,

        "scores": scores,

        "sheets_synced": sheets_ok,

    }), 201


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@app.route(
    "/api/devices",
    methods=["GET"]
)
def list_devices():

    return jsonify(
        db.list_devices()
    )


# ---------------------------------------------------------------------------
# Latest reading
# ---------------------------------------------------------------------------

@app.route(
    "/api/devices/<device_id>/latest",
    methods=["GET"]
)
def latest(device_id):

    reading = db.get_latest_reading(
        device_id
    )

    if not reading:

        return jsonify({
            "error": "no readings yet for this device"
        }), 404

    # ---------------------------------------------------------
    # IMPORTANT:
    #
    # Use the crop saved WITH THIS READING.
    #
    # This prevents a Wheat reading from becoming a Rice
    # reading after the server restarts.
    # ---------------------------------------------------------

    reading_crop = reading.get(
        "crop_type"
    )

    (
        crop_name,
        crop_requirements,
        ranges,
    ) = get_crop_context(

        device_id,

        reading_crop,

    )

    # ---------------------------------------------------------
    # Analyze using the correct crop
    # ---------------------------------------------------------

    scores, overall = analysis.score_reading(

        reading,

        ranges,

    )

    # ---------------------------------------------------------
    # Generate explanations
    # ---------------------------------------------------------

    explanations = analysis.explain_reading(

        reading,

        scores,

        ranges,

    )

    return jsonify({

        "reading": reading,

        "crop": crop_name,

        "crop_requirements": crop_requirements,

        "scores": scores,

        "overall_score": overall,

        "explanations": explanations,

    })


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@app.route(
    "/api/devices/<device_id>/history",
    methods=["GET"]
)
def history(device_id):

    try:

        hours = int(
            request.args.get(
                "hours",
                24,
            )
        )

    except ValueError:

        return jsonify({
            "error": "hours must be a number"
        }), 400

    rows = db.get_history(

        device_id,

        hours=hours,

    )

    return jsonify(
        rows
    )


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

@app.route(
    "/api/devices/<device_id>/recommendations",
    methods=["GET"]
)
def recommendations(device_id):

    reading = db.get_latest_reading(
        device_id
    )

    if not reading:

        return jsonify([])

    # ---------------------------------------------------------
    # Use crop saved with latest reading
    # ---------------------------------------------------------

    reading_crop = reading.get(
        "crop_type"
    )

    (
        crop_name,
        crop_requirements,
        ranges,
    ) = get_crop_context(

        device_id,

        reading_crop,

    )

    # ---------------------------------------------------------
    # Score using correct crop
    # ---------------------------------------------------------

    scores, overall = analysis.score_reading(

        reading,

        ranges,

    )

    # ---------------------------------------------------------
    # Generate recommendations
    # ---------------------------------------------------------

    recs = analysis.generate_recommendations(

        reading,

        scores,

        ranges=ranges,

    )

    return jsonify({

        "device_id": device_id,

        "crop": crop_name,

        "overall_score": overall,

        "recommendations": recs,

    })


# ---------------------------------------------------------------------------
# Optimal strategy
# ---------------------------------------------------------------------------

@app.route(
    "/api/devices/<device_id>/strategy",
    methods=["GET"]
)
def strategy(device_id):

    reading = db.get_latest_reading(
        device_id
    )

    if not reading:

        return jsonify({
            "error": "no readings yet for this device"
        }), 404

    # ---------------------------------------------------------
    # Use crop saved with latest reading
    # ---------------------------------------------------------

    reading_crop = reading.get(
        "crop_type"
    )

    (
        crop_name,
        crop_requirements,
        ranges,
    ) = get_crop_context(

        device_id,

        reading_crop,

    )

    # ---------------------------------------------------------
    # Score using correct crop
    # ---------------------------------------------------------

    scores, overall = analysis.score_reading(

        reading,

        ranges,

    )

    # ---------------------------------------------------------
    # Generate recommendations
    # ---------------------------------------------------------

    recs = analysis.generate_recommendations(

        reading,

        scores,

        ranges=ranges,

    )

    # ---------------------------------------------------------
    # Build optimal strategy
    # ---------------------------------------------------------

    plan = analysis.build_optimal_strategy(

        reading,

        scores,

        overall,

        recs,

    )

    return jsonify({

        "device_id": device_id,

        "crop": crop_name,

        "crop_requirements": crop_requirements,

        "strategy": plan,

    })


# ---------------------------------------------------------------------------
# QR code portal
# ---------------------------------------------------------------------------

@app.route(
    "/portal/<device_id>",
    methods=["GET"]
)
def portal(device_id):

    reading = db.get_latest_reading(
        device_id
    )

    return render_template(

        "portal.html",

        device_id=device_id,

        reading=reading,

        app_url=(

            f"{Config.PUBLIC_BASE_URL}"

            f"/app/dashboard.html?device={device_id}"

        ),

    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():

    return jsonify({

        "status": "healthy",

        "time": datetime.utcnow().isoformat(),

    })


# ---------------------------------------------------------------------------
# Test crop lookup
# ---------------------------------------------------------------------------

@app.route(
    "/api/test-crop/<crop_name>",
    methods=["GET"]
)
def test_crop(crop_name):

    requirements = sheets.get_crop_requirements(

        crop_name

    )

    if requirements is None:

        return jsonify({

            "error": f"crop '{crop_name}' not found"

        }), 404

    return jsonify(
        requirements
    )


# ---------------------------------------------------------------------------
# Run locally
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    app.run(

        host=Config.HOST,

        port=Config.PORT,

        debug=Config.DEBUG,

    )