import pytest

from app import create_app
from data_sources.playcricket_public import PlayCricketPublicSource
from models import MatchFormat


@pytest.mark.parametrize("name", ["Three Day", "Four Day", "Five Day", "3 Day", "4-day", "5 Day", "Test", "Test Match", "First Class"])
def test_long_formats_keep_multi_innings_rules(name):
    fmt = MatchFormat.from_source(name, 50)
    assert fmt.is_multi_day
    assert not fmt.is_limited_overs
    assert fmt.overs_limit is None


@pytest.mark.parametrize("days,label", [(2, "Two Day"), (3, "Two Day +"), (4, "Two Day +"), (5, "Two Day +")])
def test_scheduled_playing_days_set_label(days, label):
    raw = {"id": "game", "matchType": "Two Day", "status": "LIVE", "teams": [{"displayName": "WA"}, {"displayName": "NSW"}],
           "matchSchedule": [{"matchDay": i, "startDateTime": f"2026-10-{18+i:02}T13:30:00+11:00"} for i in range(1, days + 1)]}
    match = PlayCricketPublicSource()._map_match(raw, "Australia/Sydney")
    assert match.match_type == label
    assert match.match_format.is_multi_day
    class Service:
        def matches_for_date(self, *args): return [match]
    body = create_app(Service()).test_client().get("/").text
    assert f"<span>{label}</span>" in body


def test_weekend_gap_duplicates_and_missing_dates_do_not_invent_duration():
    source = PlayCricketPublicSource()
    raw = {"matchType": "Two Day", "matchSchedule": [
        {"startDateTime": "2026-10-17T11:00:00+11:00"},
        {"startDateTime": "2026-10-24T11:00:00+11:00"},
        {"startDateTime": "2026-10-24T11:00:00+11:00"}, {}]}
    assert source._scheduled_match_type(raw) == "Two Day"
    assert source._scheduled_match_type({"matchType": "Two Day"}) == "Two Day"
    assert source._scheduled_match_type({"matchType": "Two Day"}, "Four Day") == "Four Day"
    raw["matchType"] = "T20"
    assert source._scheduled_match_type(raw) == "T20"
    raw["matchType"] = "Four Day"
    assert source._scheduled_match_type(raw) == "Four Day"


def test_scorecard_enriches_generic_fixture_duration(monkeypatch):
    source = PlayCricketPublicSource()
    raw = {"id": "game", "matchType": "Two Day", "teams": []}
    match = source._map_match(raw, "Australia/Sydney")
    detail = {**raw, "innings": [], "matchSchedule": [
        {"startDateTime": f"2026-10-{day:02}T11:00:00+11:00"} for day in range(19, 23)]}
    monkeypatch.setattr(source, "_get", lambda *args, **kwargs: detail)
    source.add_scorecard(match)
    assert match.match_type == "Two Day +"
    assert match.match_format.is_multi_day
