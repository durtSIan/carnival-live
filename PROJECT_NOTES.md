# Carnival Live Project Notes

## Proven public testing endpoints

Grade match list:

```text
https://grassrootsapiproxy.cricket.com.au/scores/grades/{grade_id}/matches?jsconfig=eccn:true
```

Match detail with scorecard:

```text
https://grassrootsapiproxy.cricket.com.au/scores/matches/{match_id}?responseModifier=includeScorecard&jsconfig=eccn:true
```

Grade detail, including the source grade name and owning organisation logo:

```text
https://grassrootsapiproxy.cricket.com.au/fixturesladders/grades/{grade_id}?jsconfig=eccn:true
```

Ball-by-ball was found but is not needed for Carnival Live v0.13.

## Current useful fields from scorecard endpoint

- `status`
- `matchSummary.teams[].displayName`
- `matchSummary.teams[].isBatting`
- `matchSummary.teams[].scoreText`
- `matchSummary.teams[].wonToss`
- `matchSummary.resultText`
- `innings[].inningsCloseType`
- `innings[].runsScored`
- `innings[].numberOfWicketsFallen`
- `innings[].oversBowled`
- `innings[].batting[].playerShortName`
- `innings[].batting[].runsScored`
- `innings[].batting[].ballsFaced`
- `innings[].batting[].isOnStrike`
- `innings[].batting[].isOnNonStrike`
- `innings[].bowling[].playerShortName`
- `innings[].bowling[].isBowling`
- `innings[].bowling[].bowlOrder`
- `innings[].bowling[].oversBowled`
- `innings[].bowling[].runsConceded`
- `innings[].bowling[].wicketsTaken`

## Short-term testing route

Use the public Play Cricket / Cricket Australia grassroots proxy route for testing live games where we do not control the organisation credentials.

## Long-term product route

For the real CCNSW Carnival Live app, use the official PlayHQ API with:

```text
tenant: ca
credentials: CCNSW PlayHQ Client ID
```

## Confirmed One Day over-limit enrichment

The PlayHQ V2 public game summary exposes the configured innings limit as:

```text
data.periods[].teams[].statistics[
  { "type": "OVER_LIMIT", "value": 45 }
]
```

Official public endpoints used:

```text
GET https://api.playhq.com/v1/organisations/{id}/seasons
GET https://api.playhq.com/v1/seasons/{id}/grades
GET https://api.playhq.com/v2/grades/{id}/games
GET https://api.playhq.com/v2/games/{id}/summary
```

Headers:

```text
x-api-key: configured PlayHQ public API key
x-phq-tenant: ca
```

Play Cricket and PlayHQ use different IDs. Carnival Live maps them by:

1. reading the grade name and owning organisation logo from Play Cricket;
2. extracting the PlayHQ organisation UUID from the Cloudinary logo path;
3. matching the active PlayHQ season and grade by name;
4. matching the game by team names and scheduled date;
5. reading `OVER_LIMIT` from the current batting period.

This was verified end-to-end on 24 July 2026 with the Interstate O50 Quad
Series Challenge (Mackay). The completed NSW O50 v Victoria Over 50 Men game
returned an authoritative limit of 45 overs for both innings.

## Architecture decision

Keep the data source replaceable:

```text
data_sources/playcricket_public.py   # testing route
data_sources/playhq_official.py      # long-term CCNSW route
```

The dashboard should consume a clean match object and not care which data source produced it.

## v0.7 compact output decision

The console display no longer prints Venue, Match ID, or URL.

The data is not removed:
- `match_id` stays in the `CarnivalMatch` object.
- `playcricket_url` stays in the `CarnivalMatch` object.
- both are still included in `--save-clean-json`.

This lets the eventual app use those fields for click-through navigation without cluttering the live display.


## v0.8 compact score extras

The compact display now removes the Match text line.

Under the current batters and current/recent bowlers it adds:
- top two dismissed batters by runs
- best two bowling figures by wickets, then fewer runs

Top dismissed batters are only displayed if one or more batters are out.


## v0.11 display fixes

- Current not-out batters keep their `*`.
- Top dismissed batters use a separate display formatter so they do not show `*`.
- Best bowling lines no longer repeat bowlers already shown in the recent bowler section.


## v0.10 bug fix

The v0.9 generated script accidentally placed `@dataclass` above `dismissed_batter_display()` instead of above `BowlerInfo`.

v0.10 fixes that syntax/runtime problem.


## v0.11 score line and run rate

The score line now displays:

```text
Team score (overs) RR=x.xx
```

Example:

```text
Nightcliff Div 1 0-23 (5) RR=4.60
```

The script converts cricket overs correctly:
- `4.2` means 4 overs and 2 balls.
- decimal overs = `4 + 2/6`.


## v0.12 bowler display

Bowler figures now display overs in brackets:

```text
*B Campbell 1/16 (3)
```

instead of:

```text
*B Campbell 1/16 off 3
```


## v0.13 normal display mode

The normal console output is now display-only.

Diagnostic lines are hidden unless `--debug` is used:
- GET URL
- Status code
- match counts
- startup banner
- visible-list heading
- save confirmation

This more closely matches what the app screen should display.
