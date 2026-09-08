"""
AI Verdant — Backend API

Endpoints
---------
POST /api/ingest              Hardware device pushes a sensor reading
GET  /api/devices              List registered devices
GET  /api/devices/<id>/latest  Latest reading + scores + explanations
GET  /api/devices/<id>/history?hours=24   Time-series for charts
GET  /api/devices/<id>/recommendations    Ranked recommendation list
GET  /api/devices/<id>/strategy           Elaborate optimal-strategy plan
GET  /portal/<id>              QR-code landing page (device status + sync)
GET  /healthz                  Liveness check
"""

from flask import Flask, request, jsonify, render_template, abort
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
CORS(app)  # allow the frontend (served separately) to call this API

db.init_db()


# ---------------------------------------------------------------------------
# Ingest — called by the ESP32 / Arduino, or by the QR portal's "Sync now"
# ---------------------------------------------------------------------------
@app.route("/api/ingest", methods=["POST"])
def ingest():
    key = request.headers.get("X-Device-Key")
    if key != Config.DEVICE_API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "expected JSON body"}), 400

    device_id = payload.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    data = {
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat()),
        "temperature_c": payload.get("temperature_c"),
        "humidity_pct": payload.get("humidity_pct"),
        "soil_moisture_pct": payload.get("soil_moisture_pct"),
        "ph": payload.get("ph"),
        "water_level_cm": payload.get("water_level_cm"),
        "motion_detected": payload.get("motion_detected", False),
    }

    db.upsert_device(
        device_id,
        name=payload.get("device_name"),
        farm_name=payload.get("farm_name"),
        location=payload.get("location"),
        crop_type=payload.get("crop_type"),
    )

    scores, overall = analysis.score_reading(data)
    db.insert_reading(device_id, data, overall)

    # Recommendations are recomputed and stored so /recommendations has history
    recs = analysis.generate_recommendations(data, scores)
    for r in recs:
        db.insert_recommendation(device_id, r["category"], r["severity"], r["message"], r["strategy"])

    sheets_ok = sheets.push_reading(device_id, data, overall)

    return jsonify({
        "status": "ok",
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


@app.route("/api/devices/<device_id>/latest", methods=["GET"])
def latest(device_id):
    reading = db.get_latest_reading(device_id)
    if not reading:
        return jsonify({"error": "no readings yet for this device"}), 404
    scores, overall = analysis.score_reading(reading)
    explanations = analysis.explain_reading(reading, scores)
    return jsonify({
        "reading": reading,
        "scores": scores,
        "overall_score": overall,
        "explanations": explanations,
    })


@app.route("/api/devices/<device_id>/history", methods=["GET"])
def history(device_id):
    hours = int(request.args.get("hours", 24))
    rows = db.get_history(device_id, hours=hours)
    return jsonify(rows)


@app.route("/api/devices/<device_id>/recommendations", methods=["GET"])
def recommendations(device_id):
    reading = db.get_latest_reading(device_id)
    if not reading:
        return jsonify([])
    scores, overall = analysis.score_reading(reading)
    recs = analysis.generate_recommendations(reading, scores)
    return jsonify(recs)


@app.route("/api/devices/<device_id>/strategy", methods=["GET"])
def strategy(device_id):
    reading = db.get_latest_reading(device_id)
    if not reading:
        return jsonify({"error": "no readings yet for this device"}), 404
    scores, overall = analysis.score_reading(reading)
    recs = analysis.generate_recommendations(reading, scores)
    plan = analysis.build_optimal_strategy(reading, scores, overall, recs)
    return jsonify(plan)


# ---------------------------------------------------------------------------
# QR code portal — this is the URL encoded into the QR sticker on the box
# ---------------------------------------------------------------------------
@app.route("/portal/<device_id>", methods=["GET"])
def portal(device_id):
    reading = db.get_latest_reading(device_id)
    return render_template(
        "portal.html",
        device_id=device_id,
        reading=reading,
        app_url=f"{Config.PUBLIC_BASE_URL}/app/dashboard.html?device={device_id}",
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "healthy", "time": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
