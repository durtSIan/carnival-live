from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests


UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class PlayHQPublicEnricher:
    """Resolve authoritative cricket over limits from PlayHQ's public API."""

    base_url = "https://api.playhq.com"

    def __init__(
        self,
        api_key: str,
        tenant: str = "ca",
        session: requests.Session | None = None,
        timeout: int = 20,
    ):
        self.api_key = api_key.strip()
        self.tenant = tenant.strip() or "ca"
        self.session = session or requests.Session()
        self.timeout = timeout
        self._grade_ids: dict[tuple[str, str], str | None] = {}
        self._fixtures: dict[str, dict[str, Any]] = {}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str) -> dict[str, Any]:
        response = self.session.get(
            self.base_url + path,
            headers={
                "accept": "application/json",
                "x-api-key": self.api_key,
                "x-phq-tenant": self.tenant,
                "user-agent": "CarnivalLive/1.0",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("PlayHQ returned an unexpected response.")
        return data

    @staticmethod
    def organisation_id_from_logo(logo_url: str) -> str:
        found = re.search(rf"/production/[^/]+/({UUID_PATTERN})(?:/|$)", str(logo_url), re.I)
        return found.group(1) if found else ""

    @staticmethod
    def _normalise(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

    def _playhq_grade_id(self, organisation_id: str, grade_name: str) -> str | None:
        cache_key = (organisation_id, self._normalise(grade_name))
        if cache_key in self._grade_ids:
            return self._grade_ids[cache_key]

        seasons = (self._get(f"/v1/organisations/{organisation_id}/seasons").get("data") or [])
        active = [item for item in seasons if str(item.get("status") or "").upper() == "ACTIVE"]
        candidates = active or seasons
        wanted = self._normalise(grade_name)
        result = None
        for season in candidates:
            season_id = str(season.get("id") or "")
            if not season_id:
                continue
            grades = self._get(f"/v1/seasons/{season_id}/grades").get("data") or []
            match = next(
                (item for item in grades if self._normalise(str(item.get("name") or "")) == wanted),
                None,
            )
            if match:
                result = str(match.get("id") or "") or None
                break
        self._grade_ids[cache_key] = result
        return result

    def _fixture(self, grade_id: str) -> dict[str, Any]:
        if grade_id not in self._fixtures:
            self._fixtures[grade_id] = self._get(f"/v2/grades/{grade_id}/games")
        return self._fixtures[grade_id]

    def _game_id(
        self,
        grade_id: str,
        home_team: str,
        away_team: str,
        start_date: str,
        timezone_name: str,
    ) -> str | None:
        fixture = self._fixture(grade_id)
        team_names = {
            str(team.get("id") or ""): str(team.get("name") or "")
            for team in fixture.get("teams") or []
        }
        wanted_teams = {self._normalise(home_team), self._normalise(away_team)}
        for round_item in fixture.get("rounds") or []:
            for game in round_item.get("games") or []:
                names = {
                    self._normalise(team_names.get(str(team.get("id") or ""), ""))
                    for team in game.get("teams") or []
                }
                if names != wanted_teams:
                    continue
                schedule = game.get("schedule") or []
                scheduled = str((schedule[0] if schedule else {}).get("dateTime") or "")
                if scheduled:
                    parsed = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                    if parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat() != start_date:
                        continue
                return str(game.get("id") or "") or None
        return None

    @staticmethod
    def _statistic(team: dict[str, Any], statistic_type: str) -> Any:
        item = next(
            (
                statistic
                for statistic in team.get("statistics") or []
                if str(statistic.get("type") or "").upper() == statistic_type
            ),
            None,
        )
        return item.get("value") if item else None

    def current_over_limit(
        self,
        *,
        organisation_id: str,
        grade_name: str,
        home_team: str,
        away_team: str,
        batting_team: str,
        start_date: str,
        timezone_name: str,
    ) -> int | None:
        grade_id = self._playhq_grade_id(organisation_id, grade_name)
        if not grade_id:
            return None
        game_id = self._game_id(grade_id, home_team, away_team, start_date, timezone_name)
        if not game_id:
            return None

        summary = self._get(f"/v2/games/{game_id}/summary").get("data") or {}
        names = {
            str(team.get("id") or ""): str(team.get("name") or "")
            for team in summary.get("teams") or []
        }
        batting_periods: list[dict[str, Any]] = []
        for period in summary.get("periods") or []:
            batting_periods.extend(
                team
                for team in period.get("teams") or []
                if str(team.get("discipline") or "").upper() == "BATTING"
            )
        wanted = self._normalise(batting_team)
        selected = next(
            (
                team
                for team in reversed(batting_periods)
                if self._normalise(names.get(str(team.get("id") or ""), "")) == wanted
            ),
            batting_periods[-1] if batting_periods else None,
        )
        if not selected:
            return None
        try:
            over_limit = int(self._statistic(selected, "OVER_LIMIT"))
        except (TypeError, ValueError):
            return None
        return over_limit if over_limit > 0 else None
