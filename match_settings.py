from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


CONFIRMED_GRADE_OVER_LIMITS = {
    # Interstate O50 Quad Series Challenge (Mackay), confirmed for 24 July 2026.
    "c88db389-74bb-4711-b9e2-3399d9c1b6b9": 45,
}


@dataclass(frozen=True)
class InningsParameters:
    over_limit: int | None = None
    over_limit_source: str = ""
    target_override: int | None = None
    target_source: str = ""


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def resolve_innings_parameters(
    events: Iterable[dict[str, Any]] | None,
    configured_overs: int | None = None,
) -> InningsParameters:
    """Resolve mutable scorer settings from events supplied in chronological order."""
    game_type_overs = None
    adjusted_overs = None
    target_override = None
    target_source = ""

    records = events.values() if isinstance(events, dict) else events or []
    for event in records:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "").upper()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "GAME_TYPE_SETTINGS":
            scoring = payload.get("scoringSettings") if isinstance(payload.get("scoringSettings"), dict) else {}
            candidate = _positive_int(scoring.get("overs"))
            if candidate is not None:
                game_type_overs = candidate
        elif event_type == "ADJUST_PARAMETERS":
            candidate = _positive_int(payload.get("overLimit"))
            if candidate is not None:
                adjusted_overs = candidate
            if "isCustomScoredOverridingTarget" in payload:
                if payload.get("isCustomScoredOverridingTarget") is True:
                    target_override = _positive_int(payload.get("targetScore"))
                    target_source = "adjust_parameters" if target_override is not None else ""
                else:
                    target_override = None
                    target_source = ""

    if adjusted_overs is not None:
        over_limit, source = adjusted_overs, "adjust_parameters"
    elif game_type_overs is not None:
        over_limit, source = game_type_overs, "game_type_settings"
    else:
        over_limit = _positive_int(configured_overs)
        source = "configuration" if over_limit is not None else ""

    return InningsParameters(over_limit, source, target_override, target_source)
