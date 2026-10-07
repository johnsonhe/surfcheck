# Surf Check

A chat agent that tells you whether it's worth paddling out. Name a beach town (and, if you
like, your skill level) and Surf Check pulls live ocean data, scores the surf, and gives you
a straight answer.

Built on the `gemini-web-tool-calling` starter: FastAPI + LiteLLM + Gemini
(`vertex_ai/gemini-3.5-flash-lite`). The page shows every tool call the agent makes.

## Tools

All data comes from [Open-Meteo](https://open-meteo.com/) (Geocoding, Marine and Forecast
APIs), which is free and needs no API key.

| Tool | What it does |
| --- | --- |
| `evaluate_surf_conditions(spot, skill_level)` | Live wave height, period and wind, scored 0-10 with our own rubric, plus a go / no-go verdict for your skill level. |
| `find_best_surf_days(spot, days)` | Scores each of the next 1-7 days with the same rubric and ranks them. |
| `recommend_wetsuit(spot)` | Live water temperature and the wetsuit (and booties/gloves/hood) to wear. |
| `get_tides(spot)` | Today's high and low tide times and heights (modeled). |

The scoring rubric (`score_surf` in `tools.py`): waves up to 4 points (2-6 ft is ideal),
period up to 3 points (10 s+ is clean groundswell), wind up to 3 points (under 8 mph is
glassy). The verdict also checks wave height against a limit per skill level
(beginner 3 ft, intermediate 6 ft, advanced 15 ft).

Tools never crash the agent: bad spots, inland cities, API outages and bad arguments come
back as `{"error": ...}` messages that tell the model what to do next.

## Sample queries

1. "How's the surf at Montauk right now? I'm a beginner."
2. "What's the best day to surf Huntington Beach this week?" then follow up with
   "And what wetsuit do I need there?" (it remembers the spot)
3. "What wetsuit do I need in Pacifica, and when is low tide?"

## Run locally

1. A GCP project with billing and the Vertex AI API enabled.
2. `gcloud auth application-default login`
3. `uv run app.py`, then open http://localhost:8000
