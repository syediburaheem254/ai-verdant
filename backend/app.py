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


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_verdant")


app = Flask(__name__)
app.config.from_object(Config)

CORS(app)

db.init_db()


# ---------------------------------------------------------------------------
# Helper: determine the crop and analysis ranges for a device
# ---------------------------------------------------------------------------
def get_crop_context(device_id, crop_name=None):
    """
    Determine which crop is being monitored and load its requirements
    from the Google Sheets Crops worksheet.

    Priority:
        1. Explicit crop_name supplied by the current sensor payload
        2. Crop stored in the device registry
        3. Config.DEFAULT_CROP

    Returns:
        crop_name, crop_requirements, ranges
    """

    # 1. Explicit crop supplied by the current request
    selected_crop = crop_name

    # 2. Otherwise try to find the crop stored for the device
    if not selected_crop:
        try:
            devices = db.list_devices()

            for device in devices:
                if str(device.get("device_id", "")).strip() == str(device_id).strip():
                    selected_crop = device.get("crop_type")
                    break

        except Exception as e:
            logger.warning(
                "Could not determine crop from device registry: %s",
                e,
            )

    # 3. Final fallback
    selected_crop = selected_crop or Config.DEFAULT_CROP

    # Load crop requirements from Google Sheets
    crop_requirements = sheets.get_crop_requirements(selected_crop)

    # Convert the sheet row into analysis ranges
    if crop_requirements:
        ranges = analysis.ranges_from_crop_requirements(crop_requirements)
    else:
        logger.warning(
            "No requirements found for crop '%s'. Using default analysis ranges.",
            selected_crop,
        )
        ranges = analysis.RANGES

    return selected_crop, crop_requirements, ranges


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
        return jsonify({"error": "unauthorized"}), 401

    # ---------------------------------------------------------
    # 2. Read JSON payload
    # ---------------------------------------------------------
    payload = request.get_json(silent=True)

    if not payload:
        return jsonify({"error": "expected JSON body"}), 400

    # ---------------------------------------------------------
    # 3. Validate device ID
    # ---------------------------------------------------------
    device_id = payload.get("device_id")

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    # ---------------------------------------------------------
    # 4. Build sensor data
    # ---------------------------------------------------------
    data = {
        "timestamp": payload.get(
            "timestamp",
            datetime.utcnow().isoformat(),
        ),
        "temperature_c": payload.get("temperature_c"),
        "humidity_pct": payload.get("humidity_pct"),
        "soil_moisture_pct": payload.get("soil_moisture_pct"),
        "ph": payload.get("ph"),
        "water_level_cm": payload.get("water_level_cm"),
        "motion_detected": payload.get(
            "motion_detected",
            False,
        ),
    }

    # ---------------------------------------------------------
    # 5. Register / update device
    # ---------------------------------------------------------
    db.upsert_device(
        device_id,
        name=payload.get("device_name"),
        farm_name=payload.get("farm_name"),
        location=payload.get("location"),
        crop_type=payload.get("crop_type"),
    )

    # ---------------------------------------------------------
    # 6. Determine crop-specific requirements
    # ---------------------------------------------------------
    crop_name, crop_requirements, ranges = get_crop_context(
        device_id,
        payload.get("crop_type"),
    )

    # ---------------------------------------------------------
    # 7. Analyze using crop-specific ranges
    # ---------------------------------------------------------
    scores, overall = analysis.score_reading(
        data,
        ranges,
    )

    # ---------------------------------------------------------
    # 8. Store reading
    # ---------------------------------------------------------
    db.insert_reading(
        device_id,
        data,
        overall,
    )

    # ---------------------------------------------------------
    # 9. Generate crop-specific recommendations
    # ---------------------------------------------------------
    recs = analysis.generate_recommendations(
        data,
        scores,
        ranges=ranges,
    )

    for r in recs:
        db.insert_recommendation(
            device_id,
            r["category"],
            r["severity"],
            r["message"],
            r["strategy"],
        )

    # ---------------------------------------------------------
    # 10. Sync reading to Google Sheets
    # ---------------------------------------------------------
    sheets_ok = sheets.push_reading(
        device_id,
        data,
        overall,
    )

    # ---------------------------------------------------------
    # 11. Return result
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
@app.route("/api/devices", methods=["GET"])
def list_devices():
    return jsonify(db.list_devices())


# ---------------------------------------------------------------------------
# Latest reading
# ---------------------------------------------------------------------------
@app.route("/api/devices/<device_id>/latest", methods=["GET"])
def latest(device_id):

    reading = db.get_latest_reading(device_id)

    if not reading:
        return jsonify({
            "error": "no readings yet for this device"
        }), 404

    # Determine crop-specific ranges
    crop_name, crop_requirements, ranges = get_crop_context(device_id)

    # Analyze using crop-specific ranges
    scores, overall = analysis.score_reading(
        reading,
        ranges,
    )

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
@app.route("/api/devices/<device_id>/history", methods=["GET"])
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

    return jsonify(rows)


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------
@app.route("/api/devices/<device_id>/recommendations", methods=["GET"])
def recommendations(device_id):

    reading = db.get_latest_reading(device_id)

    if not reading:
        return jsonify([])

    # Determine crop-specific ranges
    crop_name, crop_requirements, ranges = get_crop_context(device_id)

    # Score using crop-specific ranges
    scores, overall = analysis.score_reading(
        reading,
        ranges,
    )

    # Generate recommendations using same crop-specific ranges
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
@app.route("/api/devices/<device_id>/strategy", methods=["GET"])
def strategy(device_id):

    reading = db.get_latest_reading(device_id)

    if not reading:
        return jsonify({
            "error": "no readings yet for this device"
        }), 404

    # Determine crop-specific ranges
    crop_name, crop_requirements, ranges = get_crop_context(device_id)

    # Score using crop-specific ranges
    scores, overall = analysis.score_reading(
        reading,
        ranges,
    )

    # Generate crop-specific recommendations
    recs = analysis.generate_recommendations(
        reading,
        scores,
        ranges=ranges,
    )

    # Build optimal strategy
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
@app.route("/portal/<device_id>", methods=["GET"])
def portal(device_id):

    reading = db.get_latest_reading(device_id)

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
@app.route("/api/test-crop/<crop_name>", methods=["GET"])
def test_crop(crop_name):

    requirements = sheets.get_crop_requirements(
        crop_name
    )

    if requirements is None:
        return jsonify({
            "error": f"crop '{crop_name}' not found"
        }), 404

    return jsonify(requirements)


# ---------------------------------------------------------------------------
# Run locally
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
    )