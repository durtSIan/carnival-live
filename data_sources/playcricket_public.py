from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from models import Batter, Bowler, InningsSummary, LiveScore, Match, MatchFormat, TeamPerformance
from match_settings import resolve_innings_parameters


class PlayCricketPublicSource:
    """Adapter for Cricket Australia's public grassroots score endpoints."""

    base_url = "https://grassrootsapiproxy.cricket.com.au"

    def __init__(self, session: requests.Session | None = None, timeout: int = 30):
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, path: str, **params: str) -> dict[str, Any]:
        response = self.session.get(
            self.base_url + path,
            params={"jsconfig": "eccn:true", **params},
            headers={
                "accept": "*/*",
                "origin": "https://play.cricket.com.au",
                "referer": "https://play.cricket.com.au/",
                "user-agent": "CarnivalLive/1.0",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Play Cricket returned an unexpected response.")
        return data

    def get_matches(self, grade_id: str, timezone_name: str) -> list[Match]:
        data = self._get(f"/scores/grades/{grade_id}/matches")
        rows = data.get("matches")
        if not isinstance(rows, list):
            raise ValueError("Play Cricket response did not include a matches list.")
        return [self._map_match(row, timezone_name) for row in rows]

    def search_organisations(self, search_text: str, limit: int = 25) -> list[dict[str, Any]]:
        data = self._get("/orgsproducts/organisation/search", searchString=search_text.strip(), limit=str(limit))
        return data.get("organisations") if isinstance(data.get("organisations"), list) else []

    def get_organisation_seasons(self, organisation_id: str) -> list[dict[str, Any]]:
        data = self._get(f"/fixturesladders/organisations/{organisation_id}/seasons")
        return data.get("seasons") if isinstance(data.get("seasons"), list) else []

    def get_organisation_grades(self, organisation_id: str, season_id: str) -> list[dict[str, Any]]:
        data = self._get(f"/fixturesladders/organisations/{organisation_id}/grades", seasonId=season_id)
        return data.get("grades") if isinstance(data.get("grades"), list) else []

    def add_scorecard(self, match: Match) -> Match:
        detail = self._get(
            f"/scores/matches/{match.match_id}",
            responseModifier="includeScorecard",
        )
        match.match_format = MatchFormat.from_source(
            match.match_type or str(detail.get("matchType") or ""),
            self._explicit_overs_limit(detail),
        )
        match.live = self.parse_scorecard(detail, match.match_format)
        match.toss_winner = self._toss_winner(detail) or match.toss_winner
        detail_status = str(detail.get("status") or "").upper()
        match.result_text = str((detail.get("matchSummary") or {}).get("resultText") or "")
        match.is_forfeit = "forfeit" in match.result_text.lower() or detail_status == "FORFEITED"
        is_final = detail_status in {"COMPLETED", "FORFEITED"} or any(
            str(innings.get("inningsCloseType") or "").upper() == "END OF MATCH"
            for innings in detail.get("innings") or []
        )
        if is_final:
            match.is_final = True
            match.result_winner, match.result_loser, match.performances = self.parse_final(detail)
        return match

    def parse_final(self, detail: dict[str, Any]) -> tuple[str, str, list[TeamPerformance]]:
        summary_teams = (detail.get("matchSummary") or {}).get("teams") or []
        detail_teams = detail.get("teams") or []
        all_teams = summary_teams or detail_teams
        team_ids = [str(team.get("id") or "") for team in all_teams]
        names = {str(team.get("id") or ""): self._team_name(team) for team in detail_teams + summary_teams}
        scores = {str(team.get("id") or ""): str(team.get("scoreText") or "") for team in summary_teams}
        performances = {
            team_id: TeamPerformance(team_name=names.get(team_id, ""), score=scores.get(team_id, ""))
            for team_id in team_ids
        }

        for innings in detail.get("innings") or []:
            batting_id = str(innings.get("battingTeamId") or "")
            if batting_id not in performances:
                performances[batting_id] = TeamPerformance(names.get(batting_id, ""))
            performances[batting_id].overs = innings.get("oversBowled", "")
            batting = sorted(
                innings.get("batting") or [],
                key=lambda row: (row.get("runsScored") or 0, -(row.get("ballsFaced") or 9999)),
                reverse=True,
            )[:2]
            performances[batting_id].batters = [
                Batter(
                    str(row.get("playerShortName") or ""), row.get("runsScored"), row.get("ballsFaced"),
                    not_out=str(row.get("dismissalType") or row.get("dismissalText") or "").lower() == "not out",
                )
                for row in batting
            ]

            bowling = sorted(
                innings.get("bowling") or [],
                key=lambda row: (
                    row.get("wicketsTaken") or 0,
                    -(row.get("runsConceded") or 0),
                    self._decimal_overs(row.get("oversBowled")),
                ),
                reverse=True,
            )[:2]
            # Keep bowling figures with the batting innings in which those
            # wickets fell, matching a conventional cricket scorecard.
            performances[batting_id].bowlers = [self._bowler(row) for row in bowling]

        winner_team = next((team for team in summary_teams if team.get("isWinner") is True), None)
        winner = self._team_name(winner_team)
        loser = next((self._team_name(team) for team in summary_teams if team is not winner_team), "") if winner else ""
        if not winner:
            result = str((detail.get("matchSummary") or {}).get("resultText") or "")
            found = re.match(r"^(.*?)\s+won by\b", result, re.I)
            winner = found.group(1).strip() if found else ""
            loser = next((self._team_name(team) for team in all_teams if self._team_name(team) != winner), "")
        ordered = sorted(performances.values(), key=lambda item: item.team_name != winner)
        return winner, loser, ordered

    @staticmethod
    def _team_name(team: dict[str, Any] | None) -> str:
        return str((team or {}).get("displayName") or (team or {}).get("name") or "").strip()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        value = re.sub(r"(\.\d{6})\d+([+-]\d{2}:\d{2}|Z)$", r"\1\2", value.strip())
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)

    def _map_match(self, raw: dict[str, Any], timezone_name: str) -> Match:
        teams = raw.get("teams") or []
        home = next((x for x in teams if x.get("isHome") is True), teams[0] if teams else {})
        away = next((x for x in teams if x.get("isHome") is False), teams[1] if len(teams) > 1 else {})
        schedule = raw.get("matchSchedule") or []
        start = (schedule[0] if schedule else {}).get("startDateTime") or ""
        local = self._parse_datetime(start).astimezone(ZoneInfo(timezone_name)) if start else None
        match_id = str(raw.get("id") or "")
        home_name, away_name = self._team_name(home), self._team_name(away)
        slug = re.sub(r"[^a-z0-9]+", "-", f"{home_name}-{away_name}".lower()).strip("-")
        return Match(
            match_id=match_id,
            playcricket_url=(f"https://play.cricket.com.au/match/{match_id}/{slug}?tab=summary" if match_id else ""),
            home_team=home_name,
            away_team=away_name,
            toss_winner=next((self._team_name(x) for x in teams if x.get("wonToss") is True), ""),
            round_name=str((raw.get("round") or {}).get("name") or ""),
            match_type=str(raw.get("matchType") or ""),
            status=str(raw.get("status") or ""),
            start_date=local.date().isoformat() if local else "",
            start_time=local.strftime("%I:%M %p").lstrip("0") if local else "",
            competition_name=str((raw.get("grade") or {}).get("name") or ""),
            result_text=str(raw.get("resultText") or ""),
            is_forfeit="forfeit" in str(raw.get("resultText") or "").lower() or str(raw.get("status") or "").upper() == "FORFEITED",
        )

    def _team_from_id(self, detail: dict[str, Any], team_id: str) -> str:
        teams = (detail.get("teams") or []) + ((detail.get("matchSummary") or {}).get("teams") or [])
        return next((self._team_name(x) for x in teams if str(x.get("id") or "") == team_id), "")

    def _toss_winner(self, detail: dict[str, Any]) -> str:
        summary = detail.get("matchSummary") or {}
        teams = (summary.get("teams") or []) + (detail.get("teams") or [])
        winner = next((self._team_name(x) for x in teams if x.get("wonToss") is True), "")
        if winner:
            return winner
        text = str(summary.get("resultText") or "")
        found = re.match(r"^(.*?)\s+won the toss\b", text, re.I)
        return found.group(1).strip() if found else ""

    @staticmethod
    def _decimal_overs(value: Any) -> float:
        text = str(value or "").strip()
        if not text:
            return 0
        if "." not in text:
            return float(text)
        overs, balls = text.split(".", 1)
        return int(overs or 0) + int(balls or 0) / 6

    @staticmethod
    def _balls_bowled(value: Any) -> int:
        text = str(value or "0").strip()
        if "." not in text:
            return int(float(text)) * 6
        overs, balls = text.split(".", 1)
        return int(overs or 0) * 6 + int(balls or 0)

    @staticmethod
    def _explicit_overs_limit(detail: dict[str, Any]) -> int | None:
        containers = [detail, detail.get("matchSummary") or {}, detail.get("matchSettings") or {}]
        for container in containers:
            for key in ("oversLimit", "numberOfOvers", "maximumOvers", "maxOvers", "oversPerInnings"):
                value = container.get(key)
                try:
                    limit = int(value)
                except (TypeError, ValueError):
                    continue
                if limit > 0:
                    return limit
        return None

    @staticmethod
    def _game_status(detail: dict[str, Any], innings: dict[str, Any] | None = None) -> str:
        candidates = [
            str((innings or {}).get("inningsCloseType") or ""),
            str(detail.get("status") or ""),
            str((detail.get("matchSummary") or {}).get("resultText") or ""),
        ]
        for raw in candidates:
            value = re.sub(r"[_-]+", " ", raw).strip()
            upper = value.upper()
            if "DRINK" in upper:
                return "Drinks break"
            if "RAIN" in upper and any(word in upper for word in ("DELAY", "SUSPEND", "INTERRUPT")):
                return "Rain delay"
            if "INNINGS BREAK" in upper:
                return "Innings break"
            if "LIGHTNING" in upper:
                return "Lightning delay"
            if upper in {"DELAY", "DELAYED"}:
                return "Delay"
            if "SUSPEND" in upper:
                return "Play suspended"
            if "INTERRUPT" in upper:
                return "Play interrupted"
        return ""

    @staticmethod
    def _bowler(row: dict[str, Any]) -> Bowler:
        return Bowler(
            name=str(row.get("playerShortName") or ""),
            wickets=row.get("wicketsTaken", 0), runs=row.get("runsConceded", 0),
            overs=row.get("oversBowled", ""), current=bool(row.get("isBowling")),
        )

    def parse_scorecard(self, detail: dict[str, Any], match_format: MatchFormat | None = None) -> LiveScore:
        innings = detail.get("innings") or []
        if not innings:
            return LiveScore(game_status=self._game_status(detail))
        current = next((x for x in innings if str(x.get("inningsCloseType") or "").upper() == "IN PROGRESS"), None)
        current = current or max(innings, key=lambda x: x.get("inningsOrder") or x.get("inningsNumber") or 0)
        ordered_innings = sorted(innings, key=lambda x: x.get("inningsOrder") or x.get("inningsNumber") or 0)
        current_index = next((index for index, item in enumerate(ordered_innings) if item is current), 0)
        match_format = match_format or MatchFormat.from_source(
            str(detail.get("matchType") or ""), self._explicit_overs_limit(detail)
        )
        parameters = resolve_innings_parameters(detail.get("events"), match_format.overs_limit)
        batting_id = str(current.get("battingTeamId") or "")
        team_innings_number = sum(
            str(item.get("battingTeamId") or "") == batting_id
            for item in ordered_innings[:current_index + 1]
        )
        def ordinal(value: int) -> str:
            suffix = "st" if value == 1 else "nd" if value == 2 else "rd" if value == 3 else "th"
            return f"{value}{suffix} innings"

        innings_label = ordinal(team_innings_number)
        target = parameters.target_override
        if match_format.is_limited_overs and current_index == 1:
            previous_runs = ordered_innings[0].get("runsScored")
            if target is None:
                target = int(previous_runs) + 1 if previous_runs is not None else None
        elif match_format.is_multi_day and current_index >= 3 and team_innings_number >= 2:
            prior = ordered_innings[:current_index]
            own_runs = sum(int(item.get("runsScored") or 0) for item in prior if str(item.get("battingTeamId") or "") == batting_id)
            opponent_runs = sum(int(item.get("runsScored") or 0) for item in prior if str(item.get("battingTeamId") or "") != batting_id)
            if opponent_runs >= own_runs:
                target = opponent_runs - own_runs + 1
        close_type = str(current.get("inningsCloseType") or "").upper()
        game_status = self._game_status(detail, current)
        overs_limit = parameters.over_limit
        innings_complete = (
            (close_type not in {"", "IN PROGRESS"} and not game_status)
            or (overs_limit is not None and self._decimal_overs(current.get("oversBowled")) >= overs_limit)
        )
        batting = current.get("batting") or []
        bowling = current.get("bowling") or []

        def is_not_out(row: dict[str, Any]) -> bool:
            return str(row.get("dismissalType") or row.get("dismissalText") or "").lower() == "not out"

        if innings_complete:
            display_batters = sorted(
                batting,
                key=lambda x: (x.get("runsScored") or 0, -(x.get("ballsFaced") or 9999)),
                reverse=True,
            )[:2]
        else:
            display_batters = [x for x in batting if x.get("isOnStrike") or x.get("isOnNonStrike")]
            if len(display_batters) < 2:
                display_batters = [x for x in batting if is_not_out(x)]
            display_batters.sort(key=lambda x: (not x.get("isOnStrike", False), x.get("batOrder") or 999))
            display_batters = display_batters[:2]
        current_batters = [
            Batter(
                str(x.get("playerShortName") or ""), x.get("runsScored"), x.get("ballsFaced"),
                bool(x.get("isOnStrike")) if not innings_complete else False,
                is_not_out(x),
            )
            for x in display_batters
        ]

        dismissed = [x for x in batting if (x.get("dismissalType") or x.get("dismissalText")) and str(x.get("dismissalType") or x.get("dismissalText")).lower() != "not out"]
        dismissed.sort(key=lambda x: (x.get("runsScored") or 0, -(x.get("ballsFaced") or 9999)), reverse=True)
        dismissed_batters = [Batter(str(x.get("playerShortName") or ""), x.get("runsScored"), x.get("ballsFaced")) for x in dismissed[:2]]

        used = [x for x in bowling if self._decimal_overs(x.get("oversBowled")) > 0]
        current_bowler = next((x for x in used if x.get("isBowling") is True), None)
        ordered = sorted(used, key=lambda x: x.get("bowlOrder") or 0, reverse=True)
        recent = ([current_bowler] if current_bowler else []) + [x for x in ordered if x is not current_bowler]
        recent = recent[:2]
        shown = {str(x.get("playerShortName") or "") for x in recent}
        best = sorted(used, key=lambda x: (x.get("wicketsTaken") or 0, -(x.get("runsConceded") or 0), self._decimal_overs(x.get("oversBowled"))), reverse=True)
        unique = best[:2] if innings_complete else recent + [x for x in best if str(x.get("playerShortName") or "") not in shown][:2]

        runs, wickets, overs = current.get("runsScored"), current.get("numberOfWicketsFallen"), current.get("oversBowled", "")
        current_runs = int(runs) if runs is not None else None
        decimal_overs = self._decimal_overs(overs)
        required_run_rate = ""
        runs_needed = None
        remaining_balls = None
        chase_metrics_confident = bool(
            match_format.is_limited_overs and target is not None and overs_limit is not None
        )
        if chase_metrics_confident and runs is not None:
            remaining_balls = max(overs_limit * 6 - self._balls_bowled(overs), 0)
            runs_needed = max(target - int(runs), 0)
            if remaining_balls > 0:
                required_run_rate = f"{runs_needed * 6 / remaining_balls:.2f}"
        summary_teams = (detail.get("matchSummary") or {}).get("teams") or []
        summary_team = next((x for x in summary_teams if str(x.get("id") or "") == batting_id), {})
        score = str(summary_team.get("scoreText") or (f"{wickets}-{runs}" if runs is not None and wickets is not None else ""))
        previous_innings = None
        two_day_context = ""
        if current_index > 0:
            previous = ordered_innings[current_index - 1]
            previous_team_id = str(previous.get("battingTeamId") or "")
            previous_runs = previous.get("runsScored")
            previous_wickets = previous.get("numberOfWicketsFallen")
            previous_close = str(previous.get("inningsCloseType") or "").upper()
            previous_score = (
                str(previous_runs)
                if previous_runs is not None and (previous_wickets == 10 or previous_close == "ALL OUT")
                else f"{previous_wickets}-{previous_runs}"
                if previous_runs is not None and previous_wickets is not None
                else ""
            )
            previous_team_innings = sum(
                str(item.get("battingTeamId") or "") == previous_team_id
                for item in ordered_innings[:current_index]
            )
            previous_innings = InningsSummary(
                self._team_from_id(detail, previous_team_id), previous_score, ordinal(previous_team_innings),
                int(previous_runs) if previous_runs is not None else None,
            )
        if match_format.is_multi_day and current_runs is not None:
            prior = ordered_innings[:current_index]
            batting_team = self._team_from_id(detail, batting_id)
            own_prior = sum(int(item.get("runsScored") or 0) for item in prior if str(item.get("battingTeamId") or "") == batting_id)
            opponent_prior = sum(int(item.get("runsScored") or 0) for item in prior if str(item.get("battingTeamId") or "") != batting_id)
            if target is not None:
                needed = max(target - current_runs, 0)
                two_day_context = f"{batting_team} need {needed}" if needed else f"{batting_team} target reached"
            elif prior:
                margin = own_prior + current_runs - opponent_prior
                if margin > 0:
                    two_day_context = f"{batting_team} lead by {margin}"
                elif margin < 0:
                    two_day_context = f"{batting_team} trail by {abs(margin)}"
                else:
                    two_day_context = "Scores level"
        return LiveScore(
            batting_team=self._team_from_id(detail, batting_id), score=score, overs=overs,
            run_rate=f"{int(runs) / decimal_overs:.2f}" if decimal_overs and runs is not None else "",
            target=target, required_run_rate=required_run_rate, runs_needed=runs_needed,
            balls_remaining=remaining_balls, wickets=wickets, runs=current_runs,
            two_day_context=two_day_context,
            innings_complete=innings_complete, game_status=game_status, innings_label=innings_label,
            current_batters=current_batters,
            dismissed_batters=[] if innings_complete else (dismissed_batters if (wickets or 0) > 0 else []),
            bowlers=[self._bowler(x) for x in unique], previous_innings=previous_innings,
            current_over_limit=overs_limit, over_limit_source=parameters.over_limit_source,
            target_source=parameters.target_source or ("calculated" if target is not None else ""),
            chase_metrics_confident=chase_metrics_confident,
        )
