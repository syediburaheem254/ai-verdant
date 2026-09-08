"""
AI Verdant — Analysis Engine

Turns raw sensor numbers into:
  1. A 0-100 score per metric + one overall condition score
  2. Plain-English explanations of what's happening and why
  3. Ranked recommendations (info / watch / action / urgent)
  4. One consolidated "optimal strategy" for the current conditions

This is intentionally rule-based (transparent, explainable, works with
zero external dependencies) rather than a black-box model — a farmer
needs to trust *why* the app is telling them something.
"""

from config import Config

RANGES = Config.IDEAL_RANGES


def ranges_from_crop_requirements(requirements):
    """Convert a Crops-sheet row into the range format used by the analysis engine."""
    if not requirements:
        return RANGES

    return {
        "temperature_c": (
            float(requirements["Temperature Min (°C)"]),
            float(requirements["Temperature Max (°C)"]),
        ),
        "humidity_pct": (
            float(requirements["Humidity Min (%)"]),
            float(requirements["Humidity Max (%)"]),
        ),
        "soil_moisture_pct": (
            float(requirements["Soil Moisture Min (%)"]),
            float(requirements["Soil Moisture Max (%)"]),
        ),
        "ph": (
            float(requirements["pH Min"]),
            float(requirements["pH Max"]),
        ),
        "water_level_cm": (
            float(requirements["Water Level Min (cm)"]),
            float(requirements["Water Level Max (cm)"]),
        ),
    }

def _score_metric(value, low, high):
    """Score 0-100: 100 = dead centre of ideal range, decays outside it."""
    if value is None:
        return None
    mid = (low + high) / 2
    half_width = (high - low) / 2
    if low <= value <= high:
        # Inside range: 85-100, peaking at the midpoint
        distance_from_mid = abs(value - mid) / half_width if half_width else 0
        return round(100 - (distance_from_mid * 15), 1)
    # Outside range: decays further the further out it is
    distance_outside = abs(value - (low if value < low else high))
    penalty = min(distance_outside / half_width * 40, 85)
    return round(max(85 - penalty, 0), 1)


def score_reading(data):
    """Returns per-metric scores (0-100) and the overall score."""
    scores = {}
    if data.get("temperature_c") is not None:
        scores["temperature_c"] = _score_metric(data["temperature_c"], *RANGES["temperature_c"])
    if data.get("humidity_pct") is not None:
        scores["humidity_pct"] = _score_metric(data["humidity_pct"], *RANGES["humidity_pct"])
    if data.get("soil_moisture_pct") is not None:
        scores["soil_moisture_pct"] = _score_metric(data["soil_moisture_pct"], *RANGES["soil_moisture_pct"])
    if data.get("ph") is not None:
        scores["ph"] = _score_metric(data["ph"], *RANGES["ph"])
    if data.get("water_level_cm") is not None:
        scores["water_level_cm"] = _score_metric(data["water_level_cm"], *RANGES["water_level_cm"])

    valid = [v for v in scores.values() if v is not None]
    overall = round(sum(valid) / len(valid), 1) if valid else None
    return scores, overall


def explain_reading(data, scores):
    """Plain-English, per-metric explanation of the current state."""
    explanations = []

    t = data.get("temperature_c")
    if t is not None:
        low, high = RANGES["temperature_c"]
        if t < low:
            explanations.append(f"Temperature is {t}°C, below the {low}-{high}°C comfort zone — plant growth may slow and root uptake weakens in cold soil.")
        elif t > high:
            explanations.append(f"Temperature is {t}°C, above the {low}-{high}°C comfort zone — expect faster water loss and heat stress on leaves.")
        else:
            explanations.append(f"Temperature is {t}°C, comfortably inside the {low}-{high}°C ideal range.")

    h = data.get("humidity_pct")
    if h is not None:
        low, high = RANGES["humidity_pct"]
        if h < low:
            explanations.append(f"Humidity is {h}%, drier than the {low}-{high}% target — plants lose moisture faster than roots can replace it.")
        elif h > high:
            explanations.append(f"Humidity is {h}%, above the {low}-{high}% target — this raises fungal disease risk.")
        else:
            explanations.append(f"Humidity is {h}%, within the healthy {low}-{high}% range.")

    sm = data.get("soil_moisture_pct")
    if sm is not None:
        low, high = RANGES["soil_moisture_pct"]
        if sm < low:
            explanations.append(f"Soil moisture is {sm}%, below {low}% — the root zone is drying out, irrigation is likely needed soon.")
        elif sm > high:
            explanations.append(f"Soil moisture is {sm}%, above {high}% — soil may be waterlogged, risking root rot and oxygen starvation.")
        else:
            explanations.append(f"Soil moisture is {sm}%, sitting well in the {low}-{high}% target band.")

    ph = data.get("ph")
    if ph is not None:
        low, high = RANGES["ph"]
        if ph < low:
            explanations.append(f"Soil pH is {ph}, more acidic than the {low}-{high} target — nutrient uptake (especially phosphorus) can be restricted.")
        elif ph > high:
            explanations.append(f"Soil pH is {ph}, more alkaline than the {low}-{high} target — iron and manganese may become less available to plants.")
        else:
            explanations.append(f"Soil pH is {ph}, in the ideal {low}-{high} band for most crops.")

    wl = data.get("water_level_cm")
    if wl is not None:
        explanations.append(f"Ultrasonic sensor reads {wl} cm — used to track tank level / canopy height / obstruction distance depending on your mounting.")

    if data.get("motion_detected"):
        explanations.append("Motion was detected near the field node — could be an animal intrusion or a person on-site; review the timing against expected activity.")

    return explanations


def generate_recommendations(data, scores, history=None):
    """
    Returns a list of dicts: {category, severity, message, strategy}
    severity in: info | watch | action | urgent
    """
    recs = []

    def add(category, severity, message, strategy):
        recs.append({"category": category, "severity": severity, "message": message, "strategy": strategy})

    sm = data.get("soil_moisture_pct")
    if sm is not None:
        low, high = RANGES["soil_moisture_pct"]
        if sm < low - 10:
            add("irrigation", "urgent",
                "Soil moisture critically low.",
                "Irrigate now for 15-20 minutes with drip or sprinkler, then re-check moisture in 2 hours before deciding on a second cycle.")
        elif sm < low:
            add("irrigation", "action",
                "Soil moisture trending low.",
                "Schedule a light watering session within the next few hours, ideally early morning or evening to reduce evaporation loss.")
        elif sm > high + 10:
            add("irrigation", "urgent",
                "Soil is waterlogged.",
                "Pause irrigation entirely, improve drainage if possible, and avoid heavy foot or machine traffic on saturated soil.")
        elif sm > high:
            add("irrigation", "watch",
                "Soil moisture slightly high.",
                "Hold off on the next scheduled watering and let the top layer dry before irrigating again.")

    t = data.get("temperature_c")
    if t is not None:
        low, high = RANGES["temperature_c"]
        if t > high + 5:
            add("heat_stress", "urgent",
                "Heat stress risk is high.",
                "Provide shade netting during peak sun hours (11am-3pm) and increase irrigation frequency slightly to offset faster evapotranspiration.")
        elif t > high:
            add("heat_stress", "watch",
                "Temperatures are running warm.",
                "Monitor for wilting during the afternoon; consider mulching to keep root-zone temperatures stable.")
        elif t < low:
            add("cold_stress", "action",
                "Temperatures are below the comfort zone.",
                "Use row covers overnight if a cold snap is expected, and delay any transplanting until temperatures recover.")

    h = data.get("humidity_pct")
    if h is not None:
        low, high = RANGES["humidity_pct"]
        if h > high + 10:
            add("disease_risk", "action",
                "High humidity raises fungal disease risk.",
                "Improve airflow by pruning dense foliage and avoid overhead watering; consider a preventive organic fungicide if this persists 2+ days.")
        elif h < low - 10:
            add("water_stress", "watch",
                "Very low humidity increases plant water stress.",
                "Increase watering frequency slightly and consider light misting during the hottest part of the day.")

    ph = data.get("ph")
    if ph is not None:
        low, high = RANGES["ph"]
        if ph < low:
            add("soil_chemistry", "action",
                "Soil is more acidic than ideal.",
                "Apply agricultural lime at a rate matched to your soil test, and re-test pH in 2-3 weeks before applying more.")
        elif ph > high:
            add("soil_chemistry", "action",
                "Soil is more alkaline than ideal.",
                "Apply elemental sulfur or an acidifying organic compost, and re-test pH in 2-3 weeks.")

    if data.get("motion_detected"):
        add("security", "watch",
            "Motion detected at the sensor node.",
            "Check the field camera or walk the perimeter — could be wildlife intrusion; consider a fence check if this repeats overnight.")

    if not recs:
        add("general", "info",
            "All monitored conditions are within healthy ranges.",
            "No action needed right now — maintain your current irrigation and care schedule and keep monitoring.")

    return recs


def build_optimal_strategy(data, scores, overall_score, recent_recs):
    """
    Produces the single, elaborate 'optimal strategy' page content:
    a prioritized action plan for the next 24-72 hours.
    """
    urgent = [r for r in recent_recs if r["severity"] == "urgent"]
    action = [r for r in recent_recs if r["severity"] == "action"]
    watch = [r for r in recent_recs if r["severity"] == "watch"]

    if overall_score is None:
        headline = "Not enough sensor data yet to build a strategy."
    elif overall_score >= 85:
        headline = "Conditions are excellent — focus on maintenance, not intervention."
    elif overall_score >= 65:
        headline = "Conditions are good with a few areas to fine-tune."
    elif overall_score >= 45:
        headline = "Conditions need attention in the next 24 hours."
    else:
        headline = "Conditions require immediate action."

    timeline = []
    if urgent:
        timeline.append({"window": "Next 2 hours", "items": [r["strategy"] for r in urgent]})
    if action:
        timeline.append({"window": "Today", "items": [r["strategy"] for r in action]})
    if watch:
        timeline.append({"window": "This week", "items": [r["strategy"] for r in watch]})
    if not timeline:
        timeline.append({"window": "Ongoing", "items": [
            "Keep your current irrigation and fertilization schedule.",
            "Re-check sensor readings once daily to catch early drift.",
        ]})

    return {
        "headline": headline,
        "overall_score": overall_score,
        "timeline": timeline,
    }
