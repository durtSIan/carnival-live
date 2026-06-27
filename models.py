from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class MatchFormat:
    """Source-independent rules for a match format."""

    name: str
    kind: str = "unknown"
    overs_limit: int | None = None

    @property
    def is_limited_overs(self) -> bool:
        return self.kind == "limited_overs"

    @property
    def is_multi_day(self) -> bool:
        return self.kind == "multi_day"

    @property
    def is_t20(self) -> bool:
        compact = re.sub(r"[^A-Z0-9]", "", self.name.upper())
        return compact in {"T20", "TWENTY20"}

    @classmethod
    def from_source(cls, match_type: str, overs_limit: int | None = None) -> "MatchFormat":
        name = str(match_type or "").strip()
        compact = re.sub(r"[^A-Z0-9]", "", name.upper())
        if compact in {"TWODAY", "2DAY", "MULTIDAY", "TEST"} or "TWODAY" in compact:
            return cls(name, "multi_day", None)
        t_match = re.fullmatch(r"T(\d+)", compact)
        inferred = int(t_match.group(1)) if t_match else {"TWENTY20": 20, "ODI": 50}.get(compact)
        limit = overs_limit if overs_limit and overs_limit > 0 else inferred
        if limit is not None or compact in {"ONEDAY", "LIMITEDOVERS", "ODI"}:
            return cls(name, "limited_overs", limit)
        return cls(name)


@dataclass
class Batter:
    name: str
    runs: int | None = None
    balls: int | None = None
    striker: bool = False
    not_out: bool = False


@dataclass
class Bowler:
    name: str
    wickets: int | str = 0
    runs: int | str = 0
    overs: int | float | str = ""
    current: bool = False


@dataclass
class InningsSummary:
    team_name: str
    score: str
    innings_label: str = ""


@dataclass
class LiveScore:
    batting_team: str = ""
    score: str = ""
    overs: int | float | str = ""
    run_rate: str = ""
    target: int | None = None
    required_run_rate: str = ""
    runs_needed: int | None = None
    balls_remaining: int | None = None
    wickets: int | None = None
    innings_complete: bool = False
    game_status: str = ""
    innings_label: str = ""
    current_batters: list[Batter] = field(default_factory=list)
    dismissed_batters: list[Batter] = field(default_factory=list)
    bowlers: list[Bowler] = field(default_factory=list)
    previous_innings: InningsSummary | None = None
    current_over_limit: int | None = None
    over_limit_source: str = ""
    target_source: str = ""
    chase_metrics_confident: bool = False


@dataclass
class TeamPerformance:
    team_name: str
    score: str = ""
    batters: list[Batter] = field(default_factory=list)
    bowlers: list[Bowler] = field(default_factory=list)
    overs: int | float | str = ""


@dataclass
class Match:
    match_id: str
    playcricket_url: str
    home_team: str
    away_team: str
    toss_winner: str
    round_name: str
    match_type: str
    status: str
    start_date: str
    start_time: str
    live: LiveScore | None = None
    is_final: bool = False
    result_winner: str = ""
    result_loser: str = ""
    result_text: str = ""
    is_forfeit: bool = False
    performances: list[TeamPerformance] = field(default_factory=list)
    competition_name: str = ""
    match_format: MatchFormat = field(init=False)

    def __post_init__(self) -> None:
        self.match_format = MatchFormat.from_source(self.match_type)

    @property
    def round(self) -> str:
        return self.round_name

    @property
    def batting_team(self) -> str:
        return self.live.batting_team if self.live else ""

    @property
    def score(self) -> str:
        return self.live.score if self.live else ""

    @property
    def overs(self) -> int | float | str:
        return self.live.overs if self.live else ""

    @property
    def run_rate(self) -> str:
        return self.live.run_rate if self.live else ""

    @property
    def target(self) -> int | None:
        return self.live.target if self.live else None

    @property
    def runs_required(self) -> int | None:
        return self.live.runs_needed if self.live else None

    @property
    def balls_remaining(self) -> int | None:
        return self.live.balls_remaining if self.live else None

    @property
    def required_rate(self) -> str:
        return self.live.required_run_rate if self.live else ""

    @property
    def current_batters(self) -> list[Batter]:
        return self.live.current_batters if self.live else []

    @property
    def recent_bowlers(self) -> list[Bowler]:
        return self.live.bowlers[:2] if self.live else []

    @property
    def top_batters(self) -> list[Batter]:
        if not self.live:
            return []
        return self.live.current_batters if self.live.innings_complete else self.live.dismissed_batters

    @property
    def best_bowlers(self) -> list[Bowler]:
        if not self.live:
            return []
        return self.live.bowlers[:2] if self.live.innings_complete else self.live.bowlers[2:]

    @property
    def innings_complete(self) -> bool:
        return bool(self.live and self.live.innings_complete)

    @property
    def game_status(self) -> str:
        return self.live.game_status if self.live else ""

    @property
    def innings_label(self) -> str:
        return self.live.innings_label if self.live else ""

    @property
    def previous_innings_line(self) -> str:
        if not self.match_format.is_multi_day or not self.live or not self.live.previous_innings:
            return ""
        previous = self.live.previous_innings
        return " ".join(part for part in (previous.team_name, previous.innings_label, previous.score) if part)

    @property
    def grade_label(self) -> str:
        """Compact grade name for phone cards while retaining the source name."""
        return re.sub(r"\s*\([^)]*\)\s*$", "", self.competition_name).strip()

    @property
    def grade_order(self) -> int:
        """Normalise common Australian senior grade names for club views."""
        label = self.grade_label.upper()
        if "PREMIER" in label:
            return 0
        letter = re.search(r"\b([A-Z])\s+GRADE\b", label)
        if letter:
            return ord(letter.group(1)) - ord("A") + 1
        number = re.search(r"\b(?:GRADE|DIV(?:ISION)?)\s*(\d+)\b|\b(\d+)(?:ST|ND|RD|TH)\s+GRADE\b", label)
        if number:
            return int(number.group(1) or number.group(2))
        words = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5}
        return next((rank for word, rank in words.items() if f"{word} GRADE" in label), 999)

    @property
    def has_scorecard(self) -> bool:
        return self.live is not None

    @property
    def score_line(self) -> str:
        if not self.live:
            return ""
        parts = [self.live.batting_team]
        if self.match_format.is_multi_day and self.live.innings_label:
            parts.append(self.live.innings_label)
        if self.live.score:
            parts.append(self.live.score)
        if self.live.overs != "":
            parts.append(f"({self.live.overs})")
        if self.live.run_rate:
            parts.append(f"RR={self.live.run_rate}")
        return " ".join(parts)

    @property
    def chase_line(self) -> str:
        """Show a target for limited overs; add chase metrics only for T20."""
        if not self.live or self.live.target is None or not self.match_format.is_limited_overs:
            return ""
        if not self.live.chase_metrics_confident:
            return f"Target {self.live.target}"
        if self.live.runs_needed is None:
            return ""
        if self.live.balls_remaining is None or not self.live.required_run_rate:
            return ""
        return (
            f"Target {self.live.target} | Need {self.live.runs_needed} "
            f"off {self.live.balls_remaining} | Req={self.live.required_run_rate}"
        )
