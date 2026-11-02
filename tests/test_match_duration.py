import pytest

from app import create_app
from data_sources.playcricket_public import PlayCricketPublicSource
from models import Match, MatchFormat


@pytest.mark.parametrize("name", ["Three Day", "Four Day", "Five Day", "3 Day", "4-day", "5 Day", "Test", "Test Match", "First Class"])
def test_long_formats_keep_multi_innings_rules(name):
    fmt = MatchFormat.from_source(name, 50)
    assert fmt.is_multi_day
    assert not fmt.is_limited_overs
    assert fmt.overs_limit is None


@pytest.mark.parametrize("days,label", [(2, "Two Day"), (3, "Three Day"), (4, "Four Day"), (5, "Five Day")])
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
    assert f"{match.display_date} {match.start_time}" in body


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
    assert match.match_type == "Four Day"
    assert match.match_format.is_multi_day
    assert match.display_date == "19 – 22 Oct"


@pytest.mark.parametrize("dates,expected", [
    (["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"], "03 – 06 Nov"),
    (["2026-11-03", "2026-11-04"], "03 – 04 Nov"),
    (["2026-11-03", "2026-11-10"], "03 & 10 Nov"),
    (["2026-11-03", "2026-11-10", "2026-11-17"], "03, 10 & 17 Nov"),
    (["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"], "30 Oct – 02 Nov"),
    (["2026-10-24", "2026-11-01"], "24 Oct & 01 Nov"),
    (["2026-12-31", "2027-01-01"], "31 Dec 26 – 01 Jan 27"),
    (["2026-12-24", "2027-01-01"], "24 Dec 26, 01 Jan 27"),
    (["2026-11-04", "2026-11-03", "2026-11-04", "bad"], "03 – 04 Nov"),
    (["2026-11-03"], "03-Nov-26"),
    ([], "03-Nov-26"),
])
def test_multi_day_date_display(dates, expected):
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "Two Day", "LIVE", "2026-11-03", "10:00 AM", schedule_dates=dates)
    assert match.display_date == expected


def test_single_day_format_does_not_show_multi_day_date_range():
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "One Day", "LIVE", "2026-11-03", "10:00 AM", schedule_dates=["2026-11-03", "2026-11-04"])
    assert match.display_date == "03-Nov-26"
