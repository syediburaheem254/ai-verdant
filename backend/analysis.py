"""
AI Verdant — Analysis Engine

Turns raw sensor numbers into:
    1. A 0-100 score per metric + one overall condition score
    2. Plain-English explanations of what's happening and why
    3. Ranked recommendations (info / watch / action / urgent)
    4. One consolidated "optimal strategy" for the current conditions

The engine is crop-specific when crop requirements are supplied from
Google Sheets. If no crop requirements are available, it falls back
to the default ranges defined in Config.IDEAL_RANGES.

This is intentionally rule-based (transparent, explainable, works with
zero external dependencies) rather than a black-box model — a farmer
needs to trust why the app is telling them something.
"""

from config import Config


# -------------------------------------------------------------------
# DEFAULT FALLBACK RANGES
# -------------------------------------------------------------------

RANGES = Config.IDEAL_RANGES


# -------------------------------------------------------------------
# CROP REQUIREMENT CONVERSION
# -------------------------------------------------------------------

def ranges_from_crop_requirements(requirements):
    """
    Convert one row from the Google Sheets 'Crops' worksheet into
    the range format used by the analysis engine.

    Expected keys:
        Temperature Min (°C)
        Temperature Max (°C)
        Humidity Min (%)
        Humidity Max (%)
        Soil Moisture Min (%)
        Soil Moisture Max (%)
        pH Min
        pH Max
        Water Level Min (cm)
        Water Level Max (cm)

    If requirements are missing, the default Config ranges are returned.
    """

    if not requirements:
        return RANGES

    try:
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

    except (KeyError, TypeError, ValueError):
        # If the sheet row is incomplete or malformed, safely fall back
        # to the default ranges instead of crashing the backend.
        return RANGES


# -------------------------------------------------------------------
# INDIVIDUAL METRIC SCORING
# -------------------------------------------------------------------

def _score_metric(value, low, high):
    """
    Score one sensor metric from 0-100.

    100 = exactly at the centre of the ideal range.

    Inside the ideal range:
        score gradually decreases from 100 toward 85.

    Outside the ideal range:
        score decreases more strongly based on distance from
        the acceptable range.
    """

    if value is None:
        return None

    try:
        value = float(value)
        low = float(low)
        high = float(high)
    except (TypeError, ValueError):
        return None

    # Protect against invalid ranges.
    if high < low:
        low, high = high, low

    mid = (low + high) / 2
    half_width = (high - low) / 2

    # If low == high, there is no meaningful range width.
    if half_width == 0:
        return 100.0 if value == low else 0.0

    if low <= value <= high:
        # Inside range: 85-100, peaking at midpoint.
        distance_from_mid = abs(value - mid) / half_width
        return round(100 - (distance_from_mid * 15), 1)

    # Outside range: decay as distance increases.
    distance_outside = abs(value - (low if value < low else high))

    penalty = min(
        distance_outside / half_width * 40,
        85,
    )

    return round(max(85 - penalty, 0), 1)


# -------------------------------------------------------------------
# OVERALL SENSOR SCORING
# -------------------------------------------------------------------

def score_reading(data, ranges=None):
    """
    Return:
        scores  -> dictionary containing per-metric scores
        overall -> average score across available metrics

    'ranges' should normally come from the selected crop's
    requirements in Google Sheets.

    If ranges is not supplied, the default Config ranges are used.
    """

    ranges = ranges or RANGES

    scores = {}

    # Temperature
    if data.get("temperature_c") is not None:
        scores["temperature_c"] = _score_metric(
            data["temperature_c"],
            *ranges["temperature_c"],
        )

    # Humidity
    if data.get("humidity_pct") is not None:
        scores["humidity_pct"] = _score_metric(
            data["humidity_pct"],
            *ranges["humidity_pct"],
        )

    # Soil moisture
    if data.get("soil_moisture_pct") is not None:
        scores["soil_moisture_pct"] = _score_metric(
            data["soil_moisture_pct"],
            *ranges["soil_moisture_pct"],
        )

    # pH
    if data.get("ph") is not None:
        scores["ph"] = _score_metric(
            data["ph"],
            *ranges["ph"],
        )

    # Water level
    if data.get("water_level_cm") is not None:
        scores["water_level_cm"] = _score_metric(
            data["water_level_cm"],
            *ranges["water_level_cm"],
        )

    # Calculate overall score only from valid metrics.
    valid = [
        value
        for value in scores.values()
        if value is not None
    ]

    overall = (
        round(sum(valid) / len(valid), 1)
        if valid
        else None
    )

    return scores, overall


# -------------------------------------------------------------------
# PLAIN-ENGLISH EXPLANATIONS
# -------------------------------------------------------------------

def explain_reading(data, scores, ranges=None):
    """
    Generate plain-English explanations for the current sensor state.

    The explanation uses the selected crop's requirements when
    'ranges' is supplied.
    """

    ranges = ranges or RANGES

    explanations = []

    # ---------------------------------------------------------------
    # Temperature
    # ---------------------------------------------------------------

    temperature = data.get("temperature_c")

    if temperature is not None:
        low, high = ranges["temperature_c"]

        if temperature < low:
            explanations.append(
                f"Temperature is {temperature}°C, below the "
                f"{low}-{high}°C comfort zone — plant growth may "
                f"slow and root uptake can weaken in cold conditions."
            )

        elif temperature > high:
            explanations.append(
                f"Temperature is {temperature}°C, above the "
                f"{low}-{high}°C comfort zone — expect faster "
                f"water loss and increased heat stress."
            )

        else:
            explanations.append(
                f"Temperature is {temperature}°C, comfortably inside "
                f"the {low}-{high}°C ideal range."
            )

    # ---------------------------------------------------------------
    # Humidity
    # ---------------------------------------------------------------

    humidity = data.get("humidity_pct")

    if humidity is not None:
        low, high = ranges["humidity_pct"]

        if humidity < low:
            explanations.append(
                f"Humidity is {humidity}%, below the {low}-{high}% "
                f"target — plants may lose moisture faster than "
                f"roots can replace it."
            )

        elif humidity > high:
            explanations.append(
                f"Humidity is {humidity}%, above the {low}-{high}% "
                f"target — this can increase fungal disease risk."
            )

        else:
            explanations.append(
                f"Humidity is {humidity}%, within the healthy "
                f"{low}-{high}% range."
            )

    # ---------------------------------------------------------------
    # Soil Moisture
    # ---------------------------------------------------------------

    soil_moisture = data.get("soil_moisture_pct")

    if soil_moisture is not None:
        low, high = ranges["soil_moisture_pct"]

        if soil_moisture < low:
            explanations.append(
                f"Soil moisture is {soil_moisture}%, below {low}% — "
                f"the root zone is drying out and irrigation may "
                f"be needed soon."
            )

        elif soil_moisture > high:
            explanations.append(
                f"Soil moisture is {soil_moisture}%, above {high}% — "
                f"the soil may be excessively wet, increasing the "
                f"risk of root problems and poor oxygen availability."
            )

        else:
            explanations.append(
                f"Soil moisture is {soil_moisture}%, sitting within "
                f"the {low}-{high}% target band."
            )

    # ---------------------------------------------------------------
    # pH
    # ---------------------------------------------------------------

    ph = data.get("ph")

    if ph is not None:
        low, high = ranges["ph"]

        if ph < low:
            explanations.append(
                f"Soil pH is {ph}, below the {low}-{high} target — "
                f"nutrient availability may be affected."
            )

        elif ph > high:
            explanations.append(
                f"Soil pH is {ph}, above the {low}-{high} target — "
                f"some nutrients may become less available to plants."
            )

        else:
            explanations.append(
                f"Soil pH is {ph}, inside the ideal {low}-{high} band."
            )

    # ---------------------------------------------------------------
    # Water Level
    # ---------------------------------------------------------------

    water_level = data.get("water_level_cm")

    if water_level is not None:
        low, high = ranges["water_level_cm"]

        if water_level < low:
            explanations.append(
                f"Water level is {water_level} cm, below the "
                f"{low}-{high} cm target range."
            )

        elif water_level > high:
            explanations.append(
                f"Water level is {water_level} cm, above the "
                f"{low}-{high} cm target range."
            )

        else:
            explanations.append(
                f"Water level is {water_level} cm, within the "
                f"{low}-{high} cm target range."
            )

    # ---------------------------------------------------------------
    # Motion
    # ---------------------------------------------------------------

    if data.get("motion_detected"):
        explanations.append(
            "Motion was detected near the field node — this could "
            "indicate an animal intrusion or a person on-site; "
            "review the timing against expected activity."
        )

    return explanations


# -------------------------------------------------------------------
# RECOMMENDATION ENGINE
# -------------------------------------------------------------------

def generate_recommendations(
    data,
    scores,
    history=None,
    ranges=None,
):
    """
    Return a list of recommendation dictionaries.

    Each recommendation has:

        {
            "category": "...",
            "severity": "...",
            "message": "...",
            "strategy": "..."
        }

    Severity levels:
        info
        watch
        action
        urgent

    The thresholds are calculated against the selected crop's
    requirements when 'ranges' is supplied.
    """

    ranges = ranges or RANGES

    recs = []

    def add(category, severity, message, strategy):
        recs.append(
            {
                "category": category,
                "severity": severity,
                "message": message,
                "strategy": strategy,
            }
        )

    # ---------------------------------------------------------------
    # Soil Moisture / Irrigation
    # ---------------------------------------------------------------

    soil_moisture = data.get("soil_moisture_pct")

    if soil_moisture is not None:
        low, high = ranges["soil_moisture_pct"]

        if soil_moisture < low - 10:
            add(
                "irrigation",
                "urgent",
                "Soil moisture is critically low for this crop.",
                "Irrigate now according to the crop's water requirement, "
                "then re-check soil moisture before starting another cycle.",
            )

        elif soil_moisture < low:
            add(
                "irrigation",
                "action",
                "Soil moisture is below the preferred range for this crop.",
                "Schedule a light watering session within the next few "
                "hours, preferably during cooler parts of the day to "
                "reduce evaporation loss.",
            )

        elif soil_moisture > high + 10:
            add(
                "irrigation",
                "urgent",
                "Soil moisture is far above the preferred range for this crop.",
                "Pause irrigation, improve drainage if possible, and "
                "allow the root zone to recover before watering again.",
            )

        elif soil_moisture > high:
            add(
                "irrigation",
                "watch",
                "Soil moisture is above the preferred range for this crop.",
                "Hold off on the next scheduled watering and monitor "
                "the soil until moisture returns toward the target range.",
            )

    # ---------------------------------------------------------------
    # Temperature
    # ---------------------------------------------------------------

    temperature = data.get("temperature_c")

    if temperature is not None:
        low, high = ranges["temperature_c"]

        if temperature > high + 5:
            add(
                "heat_stress",
                "urgent",
                "Temperature is significantly above this crop's preferred range.",
                "Provide shade or cooling during peak heat and monitor "
                "soil moisture because water loss can increase rapidly.",
            )

        elif temperature > high:
            add(
                "heat_stress",
                "watch",
                "Temperature is above this crop's preferred range.",
                "Monitor the crop for wilting or heat stress and consider "
                "mulching or shade during the hottest part of the day.",
            )

        elif temperature < low:
            add(
                "cold_stress",
                "action",
                "Temperature is below this crop's preferred range.",
                "Protect the crop from cold conditions where practical "
                "and monitor the temperature until it returns toward "
                "the preferred range.",
            )

    # ---------------------------------------------------------------
    # Humidity
    # ---------------------------------------------------------------

    humidity = data.get("humidity_pct")

    if humidity is not None:
        low, high = ranges["humidity_pct"]

        if humidity > high + 10:
            add(
                "disease_risk",
                "action",
                "Humidity is significantly above this crop's preferred range.",
                "Improve airflow around the crop, avoid unnecessary "
                "overhead watering, and monitor closely for fungal disease.",
            )

        elif humidity < low - 10:
            add(
                "water_stress",
                "watch",
                "Humidity is significantly below this crop's preferred range.",
                "Monitor the crop for water stress and adjust irrigation "
                "carefully if soil moisture is also falling.",
            )

    # ---------------------------------------------------------------
    # pH
    # ---------------------------------------------------------------

    ph = data.get("ph")

    if ph is not None:
        low, high = ranges["ph"]

        if ph < low:
            add(
                "soil_chemistry",
                "action",
                "Soil pH is below this crop's preferred range.",
                "Consider a suitable soil amendment based on a proper "
                "soil test, then re-test the pH before applying additional "
                "amendments.",
            )

        elif ph > high:
            add(
                "soil_chemistry",
                "action",
                "Soil pH is above this crop's preferred range.",
                "Consider a suitable soil amendment based on a proper "
                "soil test, then re-test the pH before applying additional "
                "amendments.",
            )

    # ---------------------------------------------------------------
    # Water Level
    # ---------------------------------------------------------------

    water_level = data.get("water_level_cm")

    if water_level is not None:
        low, high = ranges["water_level_cm"]

        if water_level < low:
            add(
                "water_supply",
                "critical" if water_level < low - 10 else "action",
                "Water level is below the preferred range for this crop.",
                "Inspect the water supply and replenish it if necessary. "
                "Continue monitoring before the next irrigation cycle.",
            )

        elif water_level > high:
            add(
                "water_supply",
                "watch",
                "Water level is above the preferred range.",
                "Monitor the water source and drainage system and make "
                "sure excess water is not creating a field or tank problem.",
            )

    # ---------------------------------------------------------------
    # Motion / Security
    # ---------------------------------------------------------------

    if data.get("motion_detected"):
        add(
            "security",
            "watch",
            "Motion detected at the sensor node.",
            "Check the field camera or inspect the area when practical. "
            "If motion repeatedly occurs at unexpected times, inspect "
            "the perimeter for possible animal intrusion.",
        )

    # ---------------------------------------------------------------
    # No Problems
    # ---------------------------------------------------------------

    if not recs:
        add(
            "general",
            "info",
            "All monitored conditions are within the preferred ranges "
            "for the selected crop.",
            "No immediate corrective action is needed. Maintain the "
            "current crop-care schedule and continue monitoring the sensors.",
        )

    return recs


# -------------------------------------------------------------------
# OPTIMAL STRATEGY
# -------------------------------------------------------------------

def build_optimal_strategy(
    data,
    scores,
    overall_score,
    recent_recs,
):
    """
    Produce one consolidated optimal strategy for the current conditions.

    The strategy prioritizes recommendations according to severity
    and organizes them into a practical timeline.
    """

    urgent = [
        r for r in recent_recs
        if r["severity"] == "urgent"
    ]

    action = [
        r for r in recent_recs
        if r["severity"] == "action"
    ]

    watch = [
        r for r in recent_recs
        if r["severity"] == "watch"
    ]

    # ---------------------------------------------------------------
    # Overall headline
    # ---------------------------------------------------------------

    if overall_score is None:
        headline = (
            "Not enough sensor data yet to build a strategy."
        )

    elif overall_score >= 85:
        headline = (
            "Conditions are excellent — focus on maintenance, "
            "not intervention."
        )

    elif overall_score >= 65:
        headline = (
            "Conditions are good with a few areas to fine-tune."
        )

    elif overall_score >= 45:
        headline = (
            "Conditions need attention in the next 24 hours."
        )

    else:
        headline = (
            "Conditions require immediate action."
        )

    # ---------------------------------------------------------------
    # Timeline
    # ---------------------------------------------------------------

    timeline = []

    if urgent:
        timeline.append(
            {
                "window": "Next 2 hours",
                "items": [
                    r["strategy"]
                    for r in urgent
                ],
            }
        )

    if action:
        timeline.append(
            {
                "window": "Today",
                "items": [
                    r["strategy"]
                    for r in action
                ],
            }
        )

    if watch:
        timeline.append(
            {
                "window": "This week",
                "items": [
                    r["strategy"]
                    for r in watch
                ],
            }
        )

    # ---------------------------------------------------------------
    # No actions required
    # ---------------------------------------------------------------

    if not timeline:
        timeline.append(
            {
                "window": "Ongoing",
                "items": [
                    "Keep your current irrigation and crop-care schedule.",
                    "Re-check sensor readings regularly to catch early drift.",
                ],
            }
        )

    return {
        "headline": headline,
        "overall_score": overall_score,
        "timeline": timeline,
    }