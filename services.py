from __future__ import annotations

import re

import requests

from data_sources.base import CricketDataSource
from models import Match


UPCOMING = {"UPCOMING"}
HIDDEN_FINAL = {"ABANDONED", "CANCELLED", "NO RESULT"}
FINAL_STATUSES = {"COMPLETED", "FORFEITED"}


class MatchService:
    def __init__(self, source: CricketDataSource):
        self.source = source

    def matches_for_date(self, grade_id: str, selected_date: str, timezone_name: str) -> list[Match]:
        matches = self.source.get_matches(grade_id, timezone_name)
        visible = self._visible(matches, selected_date)
        return self._with_scorecards(visible)

    def matches_for_grades(
        self, grade_ids: list[str], selected_date: str, timezone_name: str, club_name: str | list[str] = "",
        grade_names: dict[str, str] | None = None,
    ) -> list[Match]:
        """Combine grade feeds, optionally retaining only one club's matches."""
        clubs = self._normalise_club_filters(club_name)
        combined: list[Match] = []
        seen: set[str] = set()
        for grade_id in grade_ids:
            grade_matches = self.source.get_matches(grade_id, timezone_name)
            grade_clubs = [
                club
                for club in clubs
                if any(
                    self._team_matches_club_filter(match.home_team, club)
                    or self._team_matches_club_filter(match.away_team, club)
                    for match in grade_matches
                )
            ]
            for match in self._visible(grade_matches, selected_date):
                if not match.competition_name and grade_names:
                    match.competition_name = grade_names.get(grade_id, "")
                if grade_clubs and not any(
                    self._team_matches_club_filter(match.home_team, club) or self._team_matches_club_filter(match.away_team, club)
                    for club in grade_clubs
                ):
                    continue
                if match.match_id in seen:
                    continue
                seen.add(match.match_id)
                combined.append(match)
        return self._with_scorecards(combined)

    @classmethod
    def _normalise_club_filters(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            raw_values = value
        else:
            raw_values = re.split(r"[,|]", value)
        filters = [cls._normalise_club_name(item) for item in raw_values]
        return [item for item in dict.fromkeys(filters) if item]

    @staticmethod
    def _normalise_club_name(value: str) -> str:
        words = re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()
        generic = {"cricket", "club", "cc", "association", "competition", "league", "inc", "incorporated"}
        return " ".join(word for word in words if word not in generic).strip()

    @classmethod
    def _team_matches_club_filter(cls, team_name: str, normalised_club: str) -> bool:
        team = cls._normalise_club_name(team_name)
        return bool(normalised_club and (normalised_club in team or team in normalised_club))

    @staticmethod
    def _visible(matches: list[Match], selected_date: str) -> list[Match]:
        return [m for m in matches if MatchService._is_visible_on_date(m, selected_date)]

    @staticmethod
    def _is_visible_on_date(match: Match, selected_date: str) -> bool:
        status = match.status.upper()
        if status in UPCOMING | HIDDEN_FINAL:
            return False
        if match.start_date == selected_date:
            return True
        if match.match_format.is_multi_day and selected_date in match.schedule_dates:
            return True
        return False

    def _with_scorecards(self, visible: list[Match]) -> list[Match]:
        results: list[Match] = []
        for match in visible:
            try:
                results.append(self.source.add_scorecard(match))
            except requests.RequestException:
                results.append(match)
        return sorted(
            results,
            key=lambda match: (
                match.status.upper() in {"COMPLETED", "FORFEITED"} or match.is_final,
                match.grade_order,
                match.start_time,
            ),
        )
