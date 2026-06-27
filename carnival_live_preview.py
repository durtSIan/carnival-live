"""
Carnival Live Preview v0.13 - Play Cricket Public Data Source

Adds:
- toss winner display: (toss Team Name)
- side-by-side batter and bowler display
- current bowler marked with *
- cleaner match display with no venue, Match ID, URL, or Match text printed
- top dismissed batters shown without not-out star and duplicate bowling lines removed

Data endpoints used:

1) Grade match list
   https://grassrootsapiproxy.cricket.com.au/scores/grades/{grade_id}/matches?jsconfig=eccn:true

2) Match detail with scorecard
   https://grassrootsapiproxy.cricket.com.au/scores/matches/{match_id}?responseModifier=includeScorecard&jsconfig=eccn:true

No ball-by-ball endpoint is used.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date
from typing import Any, Optional

import requests
from zoneinfo import ZoneInfo


DEFAULT_GRADE_ID = "213859e0-488a-40c6-a642-dcf36df09f04"
DEFAULT_TIMEZONE = "Australia/Darwin"
BASE_URL = "https://grassrootsapiproxy.cricket.com.au"
DEBUG_LOGS = False

UPCOMING_STATUSES = {"UPCOMING"}
ACTIVE_STATUSES = {
    "IN_PROGRESS",
    "IN PROGRESS",
    "LIVE",
    "INNINGS_BREAK",
    "INNINGS BREAK",
    "STUMPS",
    "RESULT_IN_PROGRESS",
}
COMPLETED_STATUSES = {
    "COMPLETED",
    "ABANDONED",
    "CANCELLED",
    "FORFEITED",
    "NO RESULT",
}


@dataclass
class BatterInfo:
    name: str = ""
    runs: int | None = None
    balls: int | None = None
    fours: int | None = None
    sixes: int | None = None
    strike_rate: str = ""
    is_striker: bool = False
    is_non_striker: bool = False

    def display(self) -> str:
        if not self.name:
            return ""
        star = "*" if self.is_striker else ""
        runs = "" if self.runs is None else str(self.runs)
        balls = "" if self.balls is None else str(self.balls)
        if balls:
            return f"{self.name} {runs}* ({balls}){star}"
        return f"{self.name} {runs}*{star}"


def dismissed_batter_display(batter: BatterInfo) -> str:
    """
    Display a dismissed/top-score batter without the not-out star.

    Example:
      R Andrew 4 (5)

    The current batters still use BatterInfo.display(), which keeps the *.
    """
    if not batter or not batter.name:
        return ""

    runs = "" if batter.runs is None else str(batter.runs)
    balls = "" if batter.balls is None else str(batter.balls)

    if balls:
        return f"{batter.name} {runs} ({balls})"

    return f"{batter.name} {runs}"


@dataclass
class BowlerInfo:
    name: str = ""
    overs: Any = ""
    maidens: Any = ""
    runs: Any = ""
    wickets: Any = ""
    economy: str = ""
    bowl_order: int | None = None
    is_bowling: bool = False

    def display(self) -> str:
        if not self.name:
            return ""

        # Cricket style: Bowler 1/16 off 3
        if self.overs != "":
            return f"{self.name} {self.wickets}/{self.runs} ({self.overs})"

        return self.name


@dataclass
class LiveScorecardInfo:
    batting_team: str = ""
    bowling_team: str = ""
    toss_winner: str = ""
    innings_name: str = ""
    innings_number: int | None = None
    innings_close_type: str = ""
    score_text: str = ""
    runs: int | None = None
    wickets: int | None = None
    overs: Any = ""
    run_rate: str = ""
    striker: BatterInfo | None = None
    non_striker: BatterInfo | None = None
    current_bowler: BowlerInfo | None = None
    recent_bowlers: list[BowlerInfo] | None = None
    top_batters: list[BatterInfo] | None = None
    top_bowlers: list[BowlerInfo] | None = None
    result_text: str = ""


@dataclass
class CarnivalMatch:
    match_id: str
    status: str
    round_name: str
    match_type: str
    start_datetime: str
    start_date: str
    start_time: str
    home_team: str
    away_team: str
    batting_team: str
    home_score: str
    away_score: str
    venue_name: str
    result_text: str
    playcricket_url: str
    toss_winner: str = ""
    live: LiveScorecardInfo | None = None


def format_time_for_display(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def parse_playcricket_datetime(value: str) -> datetime:
    value = value.strip()
    value = re.sub(r"(\.\d{6})\d+([+-]\d{2}:\d{2}|Z)$", r"\1\2", value)

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    return datetime.fromisoformat(value)


def request_json(path: str, params: Optional[dict[str, str]] = None) -> Any:
    url = BASE_URL + path
    final_params = {"jsconfig": "eccn:true"}
    if params:
        final_params.update(params)

    headers = {
        "accept": "*/*",
        "origin": "https://play.cricket.com.au",
        "referer": "https://play.cricket.com.au/",
        "user-agent": "CarnivalLivePreview/0.13",
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }

    response = requests.get(url, params=final_params, headers=headers, timeout=30)

    if DEBUG_LOGS:
        print(f"GET {response.url}")
        print(f"Status: {response.status_code}")

    response.raise_for_status()
    return response.json()


def fetch_grade_matches(grade_id: str) -> list[dict[str, Any]]:
    data = request_json(f"/scores/grades/{grade_id}/matches")
    matches = data.get("matches")
    if not isinstance(matches, list):
        raise ValueError("Response did not include a top-level matches list.")
    return matches


def fetch_match_with_scorecard(match_id: str) -> dict[str, Any]:
    data = request_json(
        f"/scores/matches/{match_id}",
        params={"responseModifier": "includeScorecard"},
    )
    if not isinstance(data, dict):
        raise ValueError("Match scorecard response was not a JSON object.")
    return data


def team_name(team: Optional[dict[str, Any]]) -> str:
    if not team:
        return ""
    return str(team.get("displayName") or team.get("name") or "").strip()


def score_text(team: Optional[dict[str, Any]]) -> str:
    if not team:
        return ""
    return str(team.get("scoreText") or "").strip()


def extract_toss_winner_from_teams(teams: list[dict[str, Any]]) -> str:
    for team in teams:
        if team.get("wonToss") is True:
            return team_name(team)
    return ""


def extract_toss_winner_from_text(result_text: str) -> str:
    if not result_text:
        return ""

    match = re.match(r"^(.*?)\s+won the toss\b", result_text.strip(), flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return ""


def extract_toss_winner(match_detail: dict[str, Any]) -> str:
    summary = match_detail.get("matchSummary") or {}

    winner = extract_toss_winner_from_teams(summary.get("teams") or [])
    if winner:
        return winner

    winner = extract_toss_winner_from_teams(match_detail.get("teams") or [])
    if winner:
        return winner

    return extract_toss_winner_from_text(str(summary.get("resultText") or ""))


def find_team_name(match_detail: dict[str, Any], team_id: str) -> str:
    for team in match_detail.get("teams") or []:
        if str(team.get("id") or "") == str(team_id):
            return team_name(team)

    for team in (match_detail.get("matchSummary") or {}).get("teams") or []:
        if str(team.get("id") or "") == str(team_id):
            return team_name(team)

    return ""


def find_current_innings(match_detail: dict[str, Any]) -> Optional[dict[str, Any]]:
    innings = match_detail.get("innings") or []
    if not innings:
        return None

    for inn in innings:
        if str(inn.get("inningsCloseType") or "").upper() == "IN PROGRESS":
            return inn

    return sorted(innings, key=lambda x: x.get("inningsOrder") or x.get("inningsNumber") or 0)[-1]


def make_batter_info(raw: Optional[dict[str, Any]]) -> Optional[BatterInfo]:
    if not raw:
        return None
    return BatterInfo(
        name=str(raw.get("playerShortName") or ""),
        runs=raw.get("runsScored"),
        balls=raw.get("ballsFaced"),
        fours=raw.get("foursScored"),
        sixes=raw.get("sixesScored"),
        strike_rate=str(raw.get("strikeRate") or ""),
        is_striker=bool(raw.get("isOnStrike")),
        is_non_striker=bool(raw.get("isOnNonStrike")),
    )


def make_bowler_info(raw: Optional[dict[str, Any]]) -> Optional[BowlerInfo]:
    if not raw:
        return None
    return BowlerInfo(
        name=str(raw.get("playerShortName") or ""),
        overs=raw.get("oversBowled", ""),
        maidens=raw.get("maidensBowled", ""),
        runs=raw.get("runsConceded", ""),
        wickets=raw.get("wicketsTaken", ""),
        economy=str(raw.get("economy") or ""),
        bowl_order=raw.get("bowlOrder"),
        is_bowling=bool(raw.get("isBowling")),
    )


def extract_recent_bowlers(bowling_rows: list[dict[str, Any]], count: int = 2) -> list[BowlerInfo]:
    """
    Extract the last/recent two bowlers available from the scorecard.

    The scorecard does not give ball sequence here, so we use `bowlOrder`.
    This usually represents the order bowlers were used. We include only bowlers
    who have bowled more than zero overs, then take the highest bowlOrder values.

    If `isBowling` is marked, that bowler will naturally be among the recent bowlers
    if their bowlOrder is one of the latest.
    """
    bowled = []
    for row in bowling_rows:
        overs = row.get("oversBowled", 0)
        try:
            overs_as_float = float(overs)
        except (TypeError, ValueError):
            overs_as_float = 0

        if overs_as_float > 0:
            bowled.append(row)

    bowled.sort(key=lambda x: x.get("bowlOrder") or 0, reverse=True)

    return [
        info for info in (make_bowler_info(row) for row in bowled[:count])
        if info is not None
    ]




def overs_to_decimal(overs_value: Any) -> float:
    """
    Convert cricket overs to decimal overs.

    Examples:
      5   -> 5.0
      4.2 -> 4 overs and 2 balls -> 4.3333
      "4.5" -> 4 overs and 5 balls -> 4.8333
    """
    if overs_value is None or overs_value == "":
        return 0.0

    text = str(overs_value).strip()

    if "." not in text:
        try:
            return float(text)
        except ValueError:
            return 0.0

    overs_part, balls_part = text.split(".", 1)

    try:
        overs = int(overs_part or 0)
        balls = int(balls_part or 0)
    except ValueError:
        return 0.0

    # In cricket, .2 means 2 balls, not 0.2 of an over.
    return overs + (balls / 6.0)


def calculate_run_rate(runs: Any, overs_value: Any) -> str:
    decimal_overs = overs_to_decimal(overs_value)

    if decimal_overs <= 0:
        return ""

    try:
        runs_int = int(runs)
    except (TypeError, ValueError):
        return ""

    return f"{runs_int / decimal_overs:.2f}"


def extract_top_dismissed_batters(batting_rows: list[dict[str, Any]], count: int = 2) -> list[BatterInfo]:
    """
    Top batting scores to display underneath the current batters.

    Only dismissed batters are included. If no batters are out yet, return an
    empty list so nothing is displayed.
    """
    dismissed = []
    for row in batting_rows:
        dismissal_type = str(row.get("dismissalType") or "").strip().lower()
        dismissal_text = str(row.get("dismissalText") or "").strip().lower()

        is_not_out = dismissal_type == "not out" or dismissal_text == "not out"
        has_dismissal = bool(dismissal_type or dismissal_text)

        if has_dismissal and not is_not_out:
            dismissed.append(row)

    dismissed.sort(
        key=lambda x: (
            x.get("runsScored") or 0,
            x.get("ballsFaced") or 9999,
        ),
        reverse=True,
    )

    return [
        info for info in (make_batter_info(row) for row in dismissed[:count])
        if info is not None
    ]


def extract_top_bowlers(bowling_rows: list[dict[str, Any]], count: int = 2) -> list[BowlerInfo]:
    """
    Best bowling figures to display underneath the current/recent bowlers.

    Sort by wickets first, then fewer runs conceded, then more overs bowled.
    """
    bowled = []
    for row in bowling_rows:
        overs = row.get("oversBowled", 0)
        try:
            overs_as_float = float(overs)
        except (TypeError, ValueError):
            overs_as_float = 0

        wickets = row.get("wicketsTaken", 0) or 0
        runs = row.get("runsConceded", 0) or 0

        if overs_as_float > 0 or wickets > 0 or runs > 0:
            bowled.append(row)

    bowled.sort(
        key=lambda x: (
            x.get("wicketsTaken") or 0,
            -(x.get("runsConceded") or 0),
            x.get("oversBowled") or 0,
        ),
        reverse=True,
    )

    return [
        info for info in (make_bowler_info(row) for row in bowled[:count])
        if info is not None
    ]


def build_score_text_from_innings(innings: dict[str, Any]) -> str:
    runs = innings.get("runsScored")
    wickets = innings.get("numberOfWicketsFallen")
    if runs is None or wickets is None:
        return ""
    return f"{wickets}-{runs}"


def extract_live_scorecard(match_detail: dict[str, Any]) -> LiveScorecardInfo:
    current = find_current_innings(match_detail)
    summary = match_detail.get("matchSummary") or {}

    result_text = str(summary.get("resultText") or "")
    toss_winner = extract_toss_winner(match_detail)

    if not current:
        return LiveScorecardInfo(result_text=result_text, toss_winner=toss_winner, recent_bowlers=[], top_batters=[], top_bowlers=[], run_rate='')

    batting_team_id = str(current.get("battingTeamId") or "")
    batting_team = find_team_name(match_detail, batting_team_id)

    summary_team = None
    for team in summary.get("teams") or []:
        if str(team.get("id") or "") == batting_team_id:
            summary_team = team
            break

    score = score_text(summary_team) if summary_team else ""
    if not score:
        score = build_score_text_from_innings(current)

    batting_rows = current.get("batting") or []

    striker_raw = next((b for b in batting_rows if b.get("isOnStrike") is True), None)
    non_striker_raw = next((b for b in batting_rows if b.get("isOnNonStrike") is True), None)

    if not striker_raw or not non_striker_raw:
        not_out = [
            b for b in batting_rows
            if str(b.get("dismissalType") or "").lower() == "not out"
            or str(b.get("dismissalText") or "").lower() == "not out"
        ]
        not_out = sorted(not_out, key=lambda x: x.get("batOrder") or 999)
        if not striker_raw and not_out:
            striker_raw = not_out[-1]
        if not non_striker_raw and len(not_out) >= 2:
            candidates = [b for b in not_out if b is not striker_raw]
            non_striker_raw = candidates[0] if candidates else None

    bowling_rows = current.get("bowling") or []
    bowler_raw = next((b for b in bowling_rows if b.get("isBowling") is True), None)
    recent_bowlers = extract_recent_bowlers(bowling_rows, count=2)
    top_batters = extract_top_dismissed_batters(batting_rows, count=2)
    top_bowlers = extract_top_bowlers(bowling_rows, count=4)
    run_rate = calculate_run_rate(current.get("runsScored"), current.get("oversBowled"))

    return LiveScorecardInfo(
        batting_team=batting_team,
        toss_winner=toss_winner,
        innings_name=str(current.get("name") or ""),
        innings_number=current.get("inningsNumber"),
        innings_close_type=str(current.get("inningsCloseType") or ""),
        score_text=score,
        runs=current.get("runsScored"),
        wickets=current.get("numberOfWicketsFallen"),
        overs=current.get("oversBowled", ""),
        run_rate=run_rate,
        striker=make_batter_info(striker_raw),
        non_striker=make_batter_info(non_striker_raw),
        current_bowler=make_bowler_info(bowler_raw),
        recent_bowlers=recent_bowlers,
        top_batters=top_batters,
        top_bowlers=top_bowlers,
        result_text=result_text,
    )


def map_match(raw: dict[str, Any], timezone_name: str) -> CarnivalMatch:
    schedule = raw.get("matchSchedule") or []
    first_day = schedule[0] if schedule else {}
    start_raw = first_day.get("startDateTime") or ""

    if start_raw:
        dt = parse_playcricket_datetime(start_raw)
        local_dt = dt.astimezone(ZoneInfo(timezone_name))
        start_date = local_dt.date().isoformat()
        start_time = format_time_for_display(local_dt)
        start_datetime = local_dt.isoformat()
    else:
        start_date = ""
        start_time = ""
        start_datetime = ""

    teams = raw.get("teams") or []
    home = next((t for t in teams if t.get("isHome") is True), teams[0] if teams else None)
    away = next((t for t in teams if t.get("isHome") is False), teams[1] if len(teams) > 1 else None)
    batting = next((t for t in teams if t.get("isBatting") is True), None)

    venue = raw.get("venue") or {}
    round_obj = raw.get("round") or {}

    match_id = str(raw.get("id") or "")
    slug = f"{team_name(home)}-{team_name(away)}".lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    playcricket_url = f"https://play.cricket.com.au/match/{match_id}/{slug}?tab=summary" if match_id else ""

    return CarnivalMatch(
        match_id=match_id,
        status=str(raw.get("status") or ""),
        round_name=str(round_obj.get("name") or ""),
        match_type=str(raw.get("matchType") or ""),
        start_datetime=start_datetime,
        start_date=start_date,
        start_time=start_time,
        home_team=team_name(home),
        away_team=team_name(away),
        batting_team=team_name(batting),
        home_score=score_text(home),
        away_score=score_text(away),
        venue_name=str(venue.get("name") or ""),
        result_text=str(raw.get("resultText") or ""),
        playcricket_url=playcricket_url,
    )


def status_bucket(status: str) -> str:
    s = status.upper()
    if s in ACTIVE_STATUSES:
        return "LIVE/CURRENT"
    if s in UPCOMING_STATUSES:
        return "UPCOMING"
    if s in COMPLETED_STATUSES:
        return "COMPLETED/FINAL"
    return "OTHER"


def bowler_display_with_current_marker(bowler: BowlerInfo) -> str:
    """
    Display bowlers as:
      *B Campbell 1/16 off 3
      J Blanchard 1/15 off 3

    The leading * marks the current bowler.
    """
    if not bowler:
        return ""

    prefix = "*" if bowler.is_bowling else ""
    return f"{prefix}{bowler.display()}"


def print_batters_and_bowlers_side_by_side(live: LiveScorecardInfo) -> None:
    """
    Console preview layout.

    Left side:
      - current not-out batters
      - then top dismissed batters, if any batters are out

    Right side:
      - last/recent two bowlers
      - then best bowling figures, excluding bowlers already shown

    No 'Batting:' header and no other section headers.
    """
    batter_lines: list[str] = []
    bowler_lines: list[str] = []
    shown_bowlers: set[str] = set()

    if live.striker:
        batter_lines.append(live.striker.display())
    if live.non_striker:
        batter_lines.append(live.non_striker.display())

    if live.top_batters:
        for batter in live.top_batters[:2]:
            text = dismissed_batter_display(batter)
            if text:
                batter_lines.append(text)

    if live.recent_bowlers:
        for bowler in live.recent_bowlers[:2]:
            text = bowler_display_with_current_marker(bowler)
            if text:
                bowler_lines.append(text)
                shown_bowlers.add(bowler.name)

    if live.top_bowlers:
        for bowler in live.top_bowlers:
            if bowler.name in shown_bowlers:
                continue

            text = bowler.display()
            if text:
                bowler_lines.append(text)
                shown_bowlers.add(bowler.name)

            if len(bowler_lines) >= 4:
                break

    if not batter_lines and not bowler_lines:
        return

    rows = max(len(batter_lines), len(bowler_lines))
    left_width = 32

    for i in range(rows):
        left = batter_lines[i] if i < len(batter_lines) else ""
        right = bowler_lines[i] if i < len(bowler_lines) else ""
        if right:
            print(f"  {left:<{left_width}}  {right}")
        else:
            print(f"  {left}")


def print_match(match: CarnivalMatch) -> None:
    print("-" * 80)

    toss_winner = match.toss_winner
    if match.live and match.live.toss_winner:
        toss_winner = match.live.toss_winner

    toss_text = f" (toss {toss_winner})" if toss_winner else ""

    print(f"{match.home_team} v {match.away_team}{toss_text}")
    print(f"{match.round_name} | {match.match_type} | {match.status} | {match.start_date} {match.start_time}")

    # Venue is deliberately not printed in the compact Carnival Live view.
    # match_id and playcricket_url are still kept inside the match object for later app linking.

    if match.live:
        live = match.live

        if live.batting_team or live.score_text or live.overs != "":
            line = ""
            if live.batting_team:
                line += live.batting_team
            if live.score_text:
                line += f" {live.score_text}"
            if live.overs != "":
                line += f" ({live.overs})"
            if live.run_rate:
                line += f" RR={live.run_rate}"
            print(line.strip())

        print_batters_and_bowlers_side_by_side(live)

        # Match text is deliberately not printed in the compact Carnival Live view.

    else:
        if match.home_score or match.away_score:
            print(f"{match.home_team}: {match.home_score or 'no score'}")
            print(f"{match.away_team}: {match.away_score or 'no score'}")

        if match.batting_team:
            print(f"Batting: {match.batting_team}")

        if match.result_text:
            print(f"Result/text: {match.result_text}")

    # Match ID and URL are not printed in the compact view.
    # They remain available in the saved JSON / internal match object.


def main() -> int:
    global DEBUG_LOGS

    parser = argparse.ArgumentParser(description="Carnival Live preview for one Play Cricket grade.")
    parser.add_argument("--grade-id", default=DEFAULT_GRADE_ID)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD. Defaults to today's date in the selected timezone.")
    parser.add_argument("--show-upcoming", action="store_true", help="Show upcoming games on the selected date for testing.")
    parser.add_argument("--show-completed", action="store_true", help="Show completed games on the selected date.")
    parser.add_argument("--fetch-scorecards", action="store_true", help="Fetch scorecard details for visible matches.")
    parser.add_argument("--save-clean-json", default=None, help="Save mapped matches to this JSON file.")
    parser.add_argument("--debug", action="store_true", help="Show fetch URLs, status codes, counts and setup details.")
    args = parser.parse_args()

    DEBUG_LOGS = args.debug

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = datetime.now(ZoneInfo(args.timezone)).date()

    if DEBUG_LOGS:
        print("Carnival Live Preview v0.13")
        print("=" * 80)
        print(f"Grade ID: {args.grade_id}")
        print(f"Timezone: {args.timezone}")
        print(f"Target date: {target_date.isoformat()}")
        print(f"Show upcoming: {args.show_upcoming}")
        print(f"Show completed: {args.show_completed}")
        print(f"Fetch scorecards: {args.fetch_scorecards}")

    raw_matches = fetch_grade_matches(args.grade_id)
    mapped = [map_match(m, args.timezone) for m in raw_matches]

    todays = [m for m in mapped if m.start_date == target_date.isoformat()]

    if DEBUG_LOGS:
        print(f"\nMatches on selected date: {len(todays)}")

    visible: list[CarnivalMatch] = []
    hidden_upcoming = 0
    hidden_completed = 0

    for match in todays:
        bucket = status_bucket(match.status)

        if bucket == "UPCOMING" and not args.show_upcoming:
            hidden_upcoming += 1
            continue

        if bucket == "COMPLETED/FINAL" and not args.show_completed:
            hidden_completed += 1
            continue

        visible.append(match)

    if DEBUG_LOGS:
        print(f"Visible matches: {len(visible)}")
        if hidden_upcoming:
            print(f"Hidden upcoming matches: {hidden_upcoming}")
        if hidden_completed:
            print(f"Hidden completed/final matches: {hidden_completed}")

    if args.fetch_scorecards and visible:
        if DEBUG_LOGS:
            print("\nFetching scorecards for visible matches")
            print("=" * 80)
        for match in visible:
            try:
                detail = fetch_match_with_scorecard(match.match_id)
                match.live = extract_live_scorecard(detail)
                match.toss_winner = match.live.toss_winner
            except Exception as exc:
                print(f"Could not fetch scorecard for {match.match_id}: {exc}")

    if args.save_clean_json:
        with open(args.save_clean_json, "w", encoding="utf-8") as f:
            json.dump([asdict(m) for m in mapped], f, indent=2, ensure_ascii=False)
        if DEBUG_LOGS:
            print(f"\nSaved clean JSON to: {args.save_clean_json}")

    if not visible:
        print("\nNo visible matches for this date using the current filters.")
        print("For testing, try:")
        print(f"  python carnival_live_preview.py --date {target_date.isoformat()} --show-upcoming")
        return 0

    if DEBUG_LOGS:
        print("\nVisible match list")
        print("=" * 80)

    for match in visible:
        print_match(match)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())