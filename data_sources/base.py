from __future__ import annotations

from typing import Protocol

from models import Match


class CricketDataSource(Protocol):
    def get_matches(self, grade_id: str, timezone_name: str) -> list[Match]: ...

    def add_scorecard(self, match: Match) -> Match: ...
