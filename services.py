from __future__ import annotations

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
        self, grade_ids: list[str], selected_date: str, timezone_name: str, club_name: str = "",
        grade_names: dict[str, str] | None = None,
    ) -> list[Match]:
        """Combine grade feeds, optionally retaining only one club's matches."""
        club = club_name.casefold().strip()
        combined: list[Match] = []
        seen: set[str] = set()
        for grade_id in grade_ids:
            for match in self._visible(self.source.get_matches(grade_id, timezone_name), selected_date):
                if not match.competition_name and grade_names:
                    match.competition_name = grade_names.get(grade_id, "")
                if club and club not in match.home_team.casefold() and club not in match.away_team.casefold():
                    continue
                if match.match_id in seen:
                    continue
                seen.add(match.match_id)
                combined.append(match)
        return self._with_scorecards(combined)

    @staticmethod
    def _visible(matches: list[Match], selected_date: str) -> list[Match]:
        carry_start_date = max(
            (
                m.start_date for m in matches
                if m.match_format.is_multi_day
                and m.start_date < selected_date
                and m.status.upper() not in UPCOMING | HIDDEN_FINAL
            ),
            default="",
        )
        return [m for m in matches if MatchService._is_visible_on_date(m, selected_date, carry_start_date)]

    @staticmethod
    def _is_visible_on_date(match: Match, selected_date: str, carry_start_date: str = "") -> bool:
        status = match.status.upper()
        if status in UPCOMING | HIDDEN_FINAL:
            return False
        if match.start_date == selected_date:
            return True
        if match.match_format.is_multi_day and match.start_date == carry_start_date:
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
