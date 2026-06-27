# Carnival Live

A compact Flask dashboard for live Play Cricket scores. The dashboard shows only games on the selected date that are currently active; upcoming and completed games are excluded.

## Run

```powershell
cd C:\Users\Strudwick\carnival_live
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. The screen refreshes every 30 seconds.

Open <http://127.0.0.1:5000/setup> to search Play Cricket organisations, choose a season and grade, and save favourite grades. The public Play Cricket search endpoint currently searches organisations (clubs, associations and competitions); grade discovery follows organisation -> season -> grade. Manual grade URL/ID entry is available under Advanced.

The default grade is `213859e0-488a-40c6-a642-dcf36df09f04` and the default timezone is `Australia/Darwin`. They can be changed with environment variables:

```powershell
$env:CARNIVAL_GRADE_ID="your-grade-id"
$env:CARNIVAL_TIMEZONE="Australia/Sydney"
python app.py
```

For historical testing, use query parameters such as:

```text
http://127.0.0.1:5000/?date=2026-06-19&grade_id=213859e0-488a-40c6-a642-dcf36df09f04
```

## Deploy to Render

This project includes `render.yaml`, so Render can create a Python web service from the GitHub repo.

Suggested first deploy:

1. Push this folder to a GitHub repo, for example `carnival-live`.
2. In Render, choose **New -> Blueprint** or **New -> Web Service**.
3. Connect the GitHub repo.
4. If using a manual web service setup, use:

```text
Build command: pip install -r requirements.txt
Start command: gunicorn "app:create_app()"
```

Render will provide an HTTPS URL such as:

```text
https://carnival-live.onrender.com
```

## Architecture

- `data_sources/playcricket_public.py` fetches and maps the public Play Cricket API.
- `models.py` defines the source-independent display model.
- `services.py` filters dates/statuses and enriches visible games with scorecards.
- `app.py`, `templates/`, and `static/` are the Flask display layer.

A future PlayHQ adapter can implement `CricketDataSource` without changing the dashboard.

### PlayHQ scorer innings parameters

`match_settings.py` resolves over limits from scorer events supplied in chronological order:

1. The latest `ADJUST_PARAMETERS.payload.overLimit` wins.
2. Otherwise use `GAME_TYPE_SETTINGS.payload.scoringSettings.overs`.
3. Otherwise use a grade/app/manual configured limit.

A custom target is accepted only from `ADJUST_PARAMETERS` when
`isCustomScoredOverridingTarget` is true and `targetScore` is valid. `oversBowled`
is progress only and is never treated as the innings limit. DLS/par is not
calculated locally; it must come directly from an authoritative data source.

## Test

```powershell
python -m pytest -q
```

The main screen intentionally omits venue, match ID, URL, match text, debug output, and ball-by-ball data. `match_id` and `playcricket_url` remain available in the internal `Match` model for a later detail page.
