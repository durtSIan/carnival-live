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

Each browser or installed PWA stores its own favourite grades and followed
clubs/teams in a signed cookie. Grade selections show every match in that
grade. Club selections add only that club's matches from the associated grades;
they never narrow a grade-wide selection. A phone, one computer and another
computer can therefore follow different feeds without accounts or passwords.

Selections are specific to that browser. Clearing its site data removes the
feed, and selections do not automatically transfer to another device. Shared
named feed links are planned as a later optional feature.

Production deployments must provide a stable `CARNIVAL_SECRET_KEY`. Render
generates this value from `render.yaml`. HTTPS deployments also set
`CARNIVAL_SECURE_COOKIES=true`.

Live Play Cricket responses are shared between personal feeds in the running
web process. Match lists are cached for 30 seconds and scorecards for 25 seconds.
The optional environment variables `CARNIVAL_MATCH_LIST_CACHE_SECONDS`,
`CARNIVAL_SCORECARD_CACHE_SECONDS`, and `CARNIVAL_STALE_CACHE_SECONDS` override
those values. Cache statistics are written to the application log every 100
cache events.

## Private usage monitoring

Monitoring is disabled until BOTH `CARNIVAL_ADMIN_PASSWORD` and
`CARNIVAL_USAGE_DB` are set in the environment. Never commit the password.
The existing `CARNIVAL_SECRET_KEY` must stay stable between deployments.

For the Render **carnival-live web service** (not the short-link static site):

1. Use a paid web instance that supports a persistent disk. The free service's
   filesystem does not preserve a SQLite database through redeploys or replacement.
2. Add a persistent disk mounted at `/var/data`.
3. Set `CARNIVAL_USAGE_DB=/var/data/carnival-usage.sqlite3`.
4. Set `CARNIVAL_ADMIN_PASSWORD` to a strong, unique administrator password.
5. Optionally set `CARNIVAL_USAGE_TIMEZONE=Australia/Sydney` (the default).
   This is independent of the cricket fixture display timezone.
6. Redeploy and open `https://carnival-live.onrender.com/admin/usage`.
   The browser login username is `admin`; use the password from step 4.
   Always access the page over HTTPS. No link to this page is shown to viewers.
7. Open a scores page, then refresh the private usage page: one device should
   appear. Check again after a redeploy to verify storage persistence.

For local testing, use an absolute writable database path outside the repository
and the same two environment variables. Database files are excluded from Git.
Removing the password disables monitoring and the heartbeat script.

The scores page sends a small heartbeat roughly once a minute while visible.
A random browser-local identifier is hashed with a server secret and the local
date before storage. The monitor records no IP addresses, user agent strings,
names, feed selections or URLs. Hosting access logs are separate from this
monitor. Multiple tabs are deduplicated; separate browsers, private sessions
and devices can count separately. Blocked browser storage or JavaScript will
undercount. Activity reports are estimates, not a count of people.

Active devices checked in within two minutes today. Peak and unique counts use
the configured reporting timezone. Daily hashed identifiers are retained for
today and yesterday, with older rows removed on subsequent heartbeats; aggregate
daily totals are retained for 90 days. The page shows the latest 14 days.
Nothing from before activation can be counted retrospectively.

Page health covers scores and setup requests, not assets or monitoring requests.
It reports server response time and counts HTTP 5xx or caught feed failures.
Cached stale scores or missing fields can still look like a successful response.
Database failures are logged without breaking the scores page. If configured
storage cannot open at startup, monitoring stays disabled and the private page
reports storage unavailable after authentication.

SQLite supports concurrent workers on **one instance sharing that disk**. This
is not a multi-instance analytics backend. Render disks restrict scaling; use a
shared database before adding instances. The existing score cache is still
process-local, so increasing worker counts needs a separate caching review.

Run monitoring checks with `python -m pytest tests/test_usage.py -q` and
`node tests/test_usage_client.js`.

## Technology stack

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
