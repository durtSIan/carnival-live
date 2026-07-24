# Carnival Live

Carnival Live is a mobile-friendly Flask dashboard that displays live scores from multiple cricket matches in one place.

It is designed for cricket carnivals, representative competitions and club rounds where several matches may be running at the same time. Users can select an association, competition, grade or club and save a preferred match feed.

The dashboard shows games on the selected date that are currently active. Upcoming and completed games are excluded from the main live display.

## Live application

Carnival Live is deployed on Render:

<https://carnival-live.onrender.com>

The Render service may take a short time to start if it has been inactive.

## Features

Carnival Live can display:

- teams and match status
- current score, wickets and overs
- run rate
- batters at the crease
- striker
- current bowlers
- toss information
- leading batting and bowling performances
- multiple live matches in one dashboard
- association, competition, grade and club feeds
- per-browser saved feed preferences using a signed, one-year cookie
- a phone-friendly Progressive Web App layout

The main screen intentionally omits venue, match ID, URL, match text, debug output and ball-by-ball data. `match_id` and `playcricket_url` remain available in the internal `Match` model for a future detail page.

## OpenAI Build Week

Carnival Live was developed and improved using OpenAI Codex with GPT-5.6.

Codex assisted with:

- planning and organising the Python and Flask application
- investigating the Play Cricket public score data
- processing JSON returned by the score endpoints
- identifying matches, innings, batters, bowlers and match states
- handling live, upcoming, completed and abandoned matches
- building association, competition, grade and club selection
- improving the phone-friendly layout
- diagnosing incorrect scores and missing information
- creating automated tests for different match situations
- improving error handling
- preparing the project for GitHub and Render deployment

GPT-5.6 was used through Codex to review code, investigate problems, suggest changes and help turn the original idea into a working application.

The running application does not currently call an AI model. Codex and GPT-5.6 were used during the design, development, debugging and testing of Carnival Live.

## Personal feeds

Each browser or installed PWA stores its own favourite grades and club/team
filters in a signed cookie. A phone, one computer and another computer can
therefore follow different feeds without accounts or passwords.

Selections are specific to that browser. Clearing its site data removes the
feed, and selections do not automatically transfer to another device. Shared
named feed links are planned as a later optional feature.

Production deployments must provide a stable `CARNIVAL_SECRET_KEY`. Render
generates this value from `render.yaml`. HTTPS deployments also set
`CARNIVAL_SECURE_COOKIES=true`.

## Technology

- Python
- Flask
- HTML
- CSS
- JavaScript
- JSON
- Play Cricket public score data
- optional PlayHQ public API over-limit enrichment
- Gunicorn
- Render
- GitHub

## Optional PlayHQ over-limit enrichment

Play Cricket remains the primary source for live matches and scorecards. If a
PlayHQ public API key is configured, Carnival Live also resolves the matching
PlayHQ game and reads the authoritative `OVER_LIMIT` statistic for the current
batting innings.

This allows One Day run chases to show:

```text
Target 226 | Need 126 off 150 | RRReq=5.04
```

Set the API key as an environment variable:

```text
PLAYHQ_API_KEY
```

The PlayHQ tenant defaults to Cricket Australia (`ca`). If enrichment cannot be
resolved, the app continues using the Play Cricket feed and does not guess the
One Day over limit.
