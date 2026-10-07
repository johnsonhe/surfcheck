"""The surf tools the harness can run, and the JSON that describes them to the model."""

import json
from datetime import datetime

import requests

# Open-Meteo is free and needs no API key.
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# The biggest waves (ft) we'd send each skill level out in.
MAX_WAVE_FT = {"beginner": 3, "intermediate": 6, "advanced": 15}

# (minimum water temp in F, wetsuit, extras), warmest first.
WETSUIT_CHART = [
    (72, "boardshorts or a bikini", "rash guard for sun"),
    (65, "2mm spring suit or wetsuit top", "none"),
    (58, "3/2mm full wetsuit", "none"),
    (52, "4/3mm full wetsuit", "booties optional"),
    (45, "5/4mm hooded wetsuit", "booties and gloves"),
    (-100, "6/5mm hooded wetsuit", "7mm booties and 5mm gloves"),
]


class ToolError(Exception):
    """A problem the model should explain or fix. run_tool turns it into {"error": ...}."""


# --- Helpers ---


def fetch_json(url: str, params: dict, service: str) -> dict:
    """GET a URL and return its JSON, or raise a ToolError the model can relay."""
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise ToolError(
            f"The {service} service is unavailable ({type(e).__name__}). "
            "Tell the user to try again in a minute."
        )


def geocode(spot: str) -> dict:
    """Turn 'Town' or 'Town, State/Country' into a display name, latitude and longitude."""
    name, _, region = (part.strip() for part in spot.partition(","))
    data = fetch_json(GEOCODE_URL, {"name": name, "count": 10}, "location lookup")
    results = data.get("results") or []
    if not results:
        raise ToolError(
            f"Spot '{name}' was not found. Use just the town or city name "
            "(e.g. 'Montauk'), or ask the user for a nearby coastal town."
        )

    def describe(r: dict) -> str:
        return f"{r['name']}, {r.get('admin1') or r.get('country', '')}"

    if region:
        matches = [r for r in results
                   if region.lower() in (str(r.get("admin1", "")).lower(),
                                         str(r.get("country", "")).lower(),
                                         str(r.get("country_code", "")).lower())]
        if not matches:
            options = "; ".join(describe(r) for r in results[:5])
            raise ToolError(f"No '{name}' found in '{region}'. Places with that name: {options}. "
                            "Retry with one of these regions or ask the user which they mean.")
        results = matches

    place = results[0]
    return {"name": describe(place), "lat": place["latitude"], "lon": place["longitude"]}


def get_marine(place: dict, params: dict) -> dict:
    """Fetch ocean data (wave heights in feet) for a geocoded place."""
    return fetch_json(
        MARINE_URL,
        {"latitude": place["lat"], "longitude": place["lon"], "length_unit": "imperial",
         "timezone": "auto", **params},
        "marine forecast",
    )


def get_wind(place: dict, params: dict) -> dict:
    """Fetch wind data (mph) for a geocoded place."""
    return fetch_json(
        FORECAST_URL,
        {"latitude": place["lat"], "longitude": place["lon"], "wind_speed_unit": "mph",
         "timezone": "auto", **params},
        "wind forecast",
    )


def no_ocean_data(place: dict) -> ToolError:
    return ToolError(
        f"No ocean data for {place['name']}. It is probably inland. "
        "Ask the user for a coastal beach or town."
    )


def score_surf(wave_ft: float, period_s: float, wind_mph: float) -> dict:
    """Our surf rubric: waves (0-4) + period (0-3) + wind (0-3) = a score out of 10."""
    if wave_ft < 1:
        wave_pts, wave_note = 0, "flat, under 1 ft"
    elif wave_ft < 2:
        wave_pts, wave_note = 2, "small but rideable"
    elif wave_ft <= 6:
        wave_pts, wave_note = 4, "ideal size"
    elif wave_ft <= 10:
        wave_pts, wave_note = 3, "big, experienced surfers only"
    else:
        wave_pts, wave_note = 0, "dangerous, over 10 ft"

    if period_s < 6:
        period_pts, period_note = 0, "short period, choppy wind swell"
    elif period_s < 10:
        period_pts, period_note = 2, "medium period, decent shape"
    else:
        period_pts, period_note = 3, "long period groundswell, clean and powerful"

    if wind_mph < 8:
        wind_pts, wind_note = 3, "light wind, glassy"
    elif wind_mph <= 12:
        wind_pts, wind_note = 2, "moderate wind, a little texture"
    elif wind_mph <= 18:
        wind_pts, wind_note = 1, "breezy, choppy"
    else:
        wind_pts, wind_note = 0, "strong wind, blown out"

    score = wave_pts + period_pts + wind_pts
    if wave_ft < 1:
        label = "Flat"
    elif score <= 3:
        label = "Poor"
    elif score <= 5:
        label = "Fair"
    elif score <= 7:
        label = "Good"
    else:
        label = "Epic"

    return {
        "score_out_of_10": score,
        "label": label,
        "reasons": {"waves": wave_note, "period": period_note, "wind": wind_note},
    }


def check_skill(skill_level: str) -> None:
    if skill_level not in MAX_WAVE_FT:
        raise ToolError(f"skill_level must be one of {list(MAX_WAVE_FT)}, got '{skill_level}'.")


def nice_time(iso: str) -> str:
    """'2026-10-07T17:00' -> '5:00 PM'"""
    return datetime.fromisoformat(iso).strftime("%I:%M %p").lstrip("0")


# --- Tools ---


def evaluate_surf_conditions(spot: str, skill_level: str = "intermediate") -> str:
    """Score the surf right now and say whether it suits the surfer's skill level."""
    check_skill(skill_level)
    place = geocode(spot)

    marine = get_marine(place, {"current": "wave_height,wave_period"})["current"]
    wave_ft, period_s = marine["wave_height"], marine["wave_period"]
    if wave_ft is None or period_s is None:
        raise no_ocean_data(place)
    wind_mph = get_wind(place, {"current": "wind_speed_10m"})["current"]["wind_speed_10m"]

    rating = score_surf(wave_ft, period_s, wind_mph)

    if wave_ft < 1:
        verdict = "skip it: too small to surf"
    elif wave_ft > MAX_WAVE_FT[skill_level]:
        verdict = f"not for you today: waves over {MAX_WAVE_FT[skill_level]} ft are too big for a {skill_level}"
    elif rating["score_out_of_10"] < 4:
        verdict = "probably skip it: conditions are poor"
    else:
        verdict = "go surf"

    return json.dumps({
        "spot": place["name"],
        "wave_height_ft": round(wave_ft, 1),
        "wave_period_s": round(period_s, 1),
        "wind_mph": round(wind_mph, 1),
        **rating,
        "skill_level": skill_level,
        "verdict": verdict,
    })


def find_best_surf_days(spot: str, days: int = 7) -> str:
    """Score each day of the coming week and rank them best to worst."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ToolError(f"days must be a whole number between 1 and 7, got '{days}'.")
    if not 1 <= days <= 7:
        raise ToolError(f"days must be between 1 and 7, got {days}.")

    place = geocode(spot)
    marine = get_marine(place, {"daily": "wave_height_max,wave_period_max", "forecast_days": days})["daily"]
    wind = get_wind(place, {"daily": "wind_speed_10m_max", "forecast_days": days})["daily"]

    ranked = []
    for i, date in enumerate(marine["time"]):
        wave_ft, period_s = marine["wave_height_max"][i], marine["wave_period_max"][i]
        wind_mph = wind["wind_speed_10m_max"][i]
        if wave_ft is None or period_s is None or wind_mph is None:
            continue
        ranked.append({
            "date": date,
            "day": datetime.fromisoformat(date).strftime("%A"),
            "max_wave_height_ft": round(wave_ft, 1),
            "max_wave_period_s": round(period_s, 1),
            "max_wind_mph": round(wind_mph, 1),
            **score_surf(wave_ft, period_s, wind_mph),
        })
    if not ranked:
        raise no_ocean_data(place)

    ranked.sort(key=lambda d: d["score_out_of_10"], reverse=True)
    return json.dumps({"spot": place["name"], "days_ranked_best_first": ranked})


def recommend_wetsuit(spot: str) -> str:
    """Pick a wetsuit from the live water temperature."""
    place = geocode(spot)
    water_c = get_marine(place, {"current": "sea_surface_temperature"})["current"]["sea_surface_temperature"]
    if water_c is None:
        raise no_ocean_data(place)

    water_f = water_c * 9 / 5 + 32
    for min_f, wetsuit, extras in WETSUIT_CHART:
        if water_f >= min_f:
            break

    return json.dumps({
        "spot": place["name"],
        "water_temp_f": round(water_f, 1),
        "wetsuit": wetsuit,
        "extras": extras,
    })


def get_tides(spot: str) -> str:
    """Find today's high and low tides from the hourly sea level."""
    place = geocode(spot)
    data = get_marine(place, {"hourly": "sea_level_height_msl", "current": "sea_level_height_msl",
                              "forecast_days": 1})
    times, heights = data["hourly"]["time"], data["hourly"]["sea_level_height_msl"]
    if None in heights:
        raise no_ocean_data(place)

    # A high tide is an hour higher than the hour before it and at least as high as the hour after.
    tides = []
    for i in range(1, len(heights) - 1):
        before, now, after = heights[i - 1], heights[i], heights[i + 1]
        if now > before and now >= after:
            tides.append({"type": "high", "time": nice_time(times[i]), "height_ft": round(now, 1)})
        elif now < before and now <= after:
            tides.append({"type": "low", "time": nice_time(times[i]), "height_ft": round(now, 1)})

    return json.dumps({
        "spot": place["name"],
        "local_time_now": nice_time(data["current"]["time"]),
        "tide_now_ft": round(data["current"]["sea_level_height_msl"], 1),
        "tides_today": tides,
        "note": "Modeled tides, accurate to about an hour. Check a local tide chart before surfing.",
    })


# What the model sees. Descriptions say what each tool returns and when to use it.
SPOT_ARG = {
    "type": "string",
    "description": "Beach town or coastal city the user asked about, optionally followed by a comma "
                   "and the state or country to avoid mix-ups, e.g. 'Montauk' or 'Santa Cruz, California'. "
                   "Use the town name, not a surf break nickname.",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_surf_conditions",
            "description": "Score the surf at a spot RIGHT NOW (0-10) from live wave height (ft), "
                           "wave period (s) and wind (mph), and give a go / no-go verdict for the "
                           "surfer's skill level. Use for 'how is the surf', 'should I go out today' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spot": SPOT_ARG,
                    "skill_level": {
                        "type": "string",
                        "enum": list(MAX_WAVE_FT),
                        "description": "The surfer's ability. Use what the user said earlier in the "
                                       "chat; default to 'intermediate' if unknown.",
                    },
                },
                "required": ["spot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_best_surf_days",
            "description": "Rank the next 1-7 days at a spot from best to worst surf, each with max "
                           "wave height (ft), period (s), wind (mph) and a 0-10 score. Use for 'when should "
                           "I go', 'best day this week', 'what about tomorrow / the weekend' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spot": SPOT_ARG,
                    "days": {
                        "type": "integer",
                        "description": "How many days ahead to check, 1-7 (today counts as day 1). Default 7.",
                    },
                },
                "required": ["spot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_wetsuit",
            "description": "Get the live water temperature (F) at a spot and the wetsuit thickness "
                           "plus booties/gloves/hood to wear. Use for 'what should I wear', 'how cold "
                           "is the water' questions.",
            "parameters": {
                "type": "object",
                "properties": {"spot": SPOT_ARG},
                "required": ["spot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tides",
            "description": "Get today's high and low tide times (local time) and heights (ft) at a "
                           "spot, plus the current local time and tide level. Use for 'when is high/low "
                           "tide' questions.",
            "parameters": {
                "type": "object",
                "properties": {"spot": SPOT_ARG},
                "required": ["spot"],
            },
        },
    },
]

# What the harness runs: tool name -> Python function.
TOOL_MAP = {
    "evaluate_surf_conditions": evaluate_surf_conditions,
    "find_best_surf_days": find_best_surf_days,
    "recommend_wetsuit": recommend_wetsuit,
    "get_tides": get_tides,
}


def run_tool(name: str, args: dict) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}"})
    try:
        return TOOL_MAP[name](**args)
    except ToolError as e:
        return json.dumps({"error": str(e)})
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})
    except Exception as e:
        return json.dumps({"error": f"{name} failed unexpectedly ({type(e).__name__}: {e}). "
                                    "Tell the user and suggest trying another spot."})
