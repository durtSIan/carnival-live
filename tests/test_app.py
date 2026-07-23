import copy
import json
from pathlib import Path

from app import club_team_grade_options, create_app, current_seasons_only, favourite_grade_selection, grade_setup_order
from data_sources.playcricket_public import PlayCricketPublicSource
from data_sources.playhq_public import PlayHQPublicEnricher
from favourites import FavouriteStore
from match_settings import resolve_innings_parameters
from models import Batter, Bowler, InningsSummary, LiveScore, Match, MatchFormat, TeamPerformance
from services import MatchService


def test_scorecard_parser_formats_cricket_values():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    live = PlayCricketPublicSource().parse_scorecard(detail)
    assert live.current_batters
    assert len({b.name for b in live.bowlers}) == len(live.bowlers)
    assert live.run_rate


def test_closed_innings_shows_only_top_two_batters_and_bowlers():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    detail["innings"][-1]["inningsCloseType"] = "ALL OUT"
    live = PlayCricketPublicSource().parse_scorecard(detail)
    batting_rows = detail["innings"][-1]["batting"]
    expected = [x["playerShortName"] for x in sorted(batting_rows, key=lambda x: (x.get("runsScored") or 0, -(x.get("ballsFaced") or 9999)), reverse=True)[:2]]
    assert live.innings_complete is True
    assert [b.name for b in live.current_batters] == expected
    assert len(live.bowlers) == 2
    assert live.dismissed_batters == []


def test_t20_quota_marks_innings_complete_when_feed_lags():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    detail["matchType"] = "T20"
    detail["innings"][-1]["inningsCloseType"] = "In Progress"
    detail["innings"][-1]["oversBowled"] = 20
    live = PlayCricketPublicSource().parse_scorecard(detail)
    assert live.innings_complete is True
    assert len(live.current_batters) == 2
    assert len(live.bowlers) == 2


def test_temporary_break_is_status_not_completed_innings():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    detail["status"] = "LIVE"
    detail["innings"][-1]["inningsCloseType"] = "Drinks Break"
    live = PlayCricketPublicSource().parse_scorecard(detail)
    assert live.game_status == "Drinks break"
    assert live.innings_complete is False


def test_second_innings_target_is_previous_total_plus_one():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    detail["matchType"] = "T20"
    first = detail["innings"][-1]
    first["inningsOrder"] = 1
    first["inningsNumber"] = 1
    first["inningsCloseType"] = "Overs Comp."
    first["runsScored"] = 86
    second = copy.deepcopy(first)
    second["inningsOrder"] = 2
    second["inningsNumber"] = 2
    second["inningsCloseType"] = "In Progress"
    second["runsScored"] = 12
    second["oversBowled"] = 2
    detail["innings"] = [first, second]
    live = PlayCricketPublicSource().parse_scorecard(detail)
    assert live.target == 87
    assert live.required_run_rate == "4.17"
    assert live.runs_needed == 75
    assert live.balls_remaining == 108


def test_one_day_chase_uses_a_configured_over_limit_when_available():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    first = detail["innings"][-1]
    first.update(inningsOrder=1, inningsNumber=1, inningsCloseType="Overs Comp.", runsScored=160)
    second = copy.deepcopy(first)
    second.update(inningsOrder=2, inningsNumber=2, inningsCloseType="In Progress", runsScored=81, oversBowled=20)
    detail["innings"] = [first, second]
    live = PlayCricketPublicSource().parse_scorecard(detail, MatchFormat.from_source("One Day", 40))
    assert live.target == 161
    assert live.runs_needed == 80 and live.balls_remaining == 120
    assert live.required_run_rate == "4.00"
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "One Day", "LIVE", "2026-06-20", "1:00 PM", live)
    assert match.chase_line == "Target 161 | Need 80 off 120 | RRReq=4.00"
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/").get_data(as_text=True)
    assert "1st innings" not in body


def test_playhq_public_summary_resolves_authoritative_over_limit():
    responses = {
        "/v1/organisations/org-id/seasons": {
            "data": [{"id": "season-id", "status": "ACTIVE"}],
        },
        "/v1/seasons/season-id/grades": {
            "data": [{"id": "grade-id", "name": "Interstate O50 Quad Series Challenge (Mackay)"}],
        },
        "/v2/grades/grade-id/games": {
            "teams": [
                {"id": "nsw", "name": "NSW O50"},
                {"id": "mackay", "name": "Mackay Masters O50"},
            ],
            "rounds": [{"games": [{
                "id": "game-id",
                "schedule": [{"dateTime": "2026-07-24T00:00:00.000Z"}],
                "teams": [{"id": "nsw"}, {"id": "mackay"}],
            }]}],
        },
        "/v2/games/game-id/summary": {
            "data": {
                "teams": [
                    {"id": "nsw", "name": "NSW O50"},
                    {"id": "mackay", "name": "Mackay Masters O50"},
                ],
                "periods": [{
                    "teams": [{
                        "id": "nsw",
                        "discipline": "BATTING",
                        "statistics": [
                            {"type": "OVER_LIMIT", "value": 45},
                            {"type": "TOTAL_OVERS", "value": 12.3},
                        ],
                    }],
                }],
            },
        },
    }

    class Response:
        def __init__(self, data): self.data = data
        def raise_for_status(self): return None
        def json(self): return self.data

    class Session:
        def get(self, url, **kwargs):
            path = url.removeprefix("https://api.playhq.com")
            return Response(responses[path])

    enricher = PlayHQPublicEnricher("api-key", session=Session())
    assert enricher.current_over_limit(
        organisation_id="org-id",
        grade_name="Interstate O50 Quad Series Challenge (Mackay)",
        home_team="Mackay Masters O50",
        away_team="NSW O50",
        batting_team="NSW O50",
        start_date="2026-07-24",
        timezone_name="Australia/Brisbane",
    ) == 45


def test_playhq_public_over_limit_enables_one_day_required_rate():
    live = LiveScore(
        batting_team="NSW O50", score="2-100", overs="20", run_rate="5.00",
        target=226, runs=100,
    )
    match = Match(
        "id", "", "Mackay Masters O50", "NSW O50", "", "Round 2", "One Day",
        "LIVE", "2026-07-24", "10:00 AM", live,
    )
    PlayCricketPublicSource._apply_over_limit(match, 45, "playhq_public")
    assert match.match_format.overs_limit == 45
    assert (live.current_over_limit, live.over_limit_source) == (45, "playhq_public")
    assert (live.runs_needed, live.balls_remaining, live.required_run_rate) == (126, 150, "5.04")
    assert match.chase_line == "Target 226 | Need 126 off 150 | RRReq=5.04"


def test_playhq_event_settings_use_latest_adjustment_then_defaults():
    events = [
        {"type": "GAME_TYPE_SETTINGS", "payload": {"scoringSettings": {"overs": 40}}},
        {"type": "ADJUST_PARAMETERS", "payload": {"overLimit": "30"}},
        {"type": "ADJUST_PARAMETERS", "payload": {
            "overLimit": "25", "targetScore": "151", "isCustomScoredOverridingTarget": True,
        }},
    ]
    resolved = resolve_innings_parameters(events, configured_overs=45)
    assert (resolved.over_limit, resolved.over_limit_source) == (25, "adjust_parameters")
    assert (resolved.target_override, resolved.target_source) == (151, "adjust_parameters")
    assert resolve_innings_parameters(events[:1], 45).over_limit == 40
    assert resolve_innings_parameters([], 35).over_limit == 35


def test_playhq_adjustment_drives_one_day_target_and_required_rate():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    first = detail["innings"][-1]
    first.update(inningsOrder=1, inningsNumber=1, inningsCloseType="Compulsory Close", runsScored=140, oversBowled=40)
    second = copy.deepcopy(first)
    second.update(inningsOrder=2, inningsNumber=2, inningsCloseType="In Progress", runsScored=50, oversBowled=10)
    detail["matchType"] = "One Day"
    detail["innings"] = [first, second]
    detail["events"] = [
        {"type": "GAME_TYPE_SETTINGS", "payload": {"scoringSettings": {"overs": 40}}},
        {"type": "ADJUST_PARAMETERS", "payload": {
            "overLimit": "25", "targetScore": "121", "isCustomScoredOverridingTarget": True,
        }},
    ]
    live = PlayCricketPublicSource().parse_scorecard(detail)
    assert (live.current_over_limit, live.over_limit_source) == (25, "adjust_parameters")
    assert (live.target, live.target_source) == (121, "adjust_parameters")
    assert (live.runs_needed, live.balls_remaining, live.required_run_rate) == (71, 90, "4.73")


def test_overs_bowled_is_never_used_as_the_one_day_limit():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    detail["matchType"] = "One Day"
    detail["events"] = []
    detail["innings"][-1]["inningsCloseType"] = "In Progress"
    detail["innings"][-1]["oversBowled"] = 40
    live = PlayCricketPublicSource().parse_scorecard(detail)
    assert live.current_over_limit is None
    assert live.innings_complete is False


def test_two_day_second_innings_is_not_mistaken_for_a_limited_overs_chase():
    detail = json.loads((Path(__file__).parents[1] / "blue_mountains_match_with_scorecard.json").read_text())
    first = detail["innings"][-1]
    first.update(inningsOrder=1, inningsNumber=1, inningsCloseType="ALL OUT", runsScored=180, battingTeamId="a")
    second = copy.deepcopy(first)
    second.update(inningsOrder=2, inningsNumber=1, inningsCloseType="In Progress", runsScored=40, battingTeamId="b")
    detail["innings"] = [first, second]
    live = PlayCricketPublicSource().parse_scorecard(detail, MatchFormat.from_source("Two Day"))
    assert live.innings_label == "1st innings"
    assert live.target is None and live.required_run_rate == ""

    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "Two Day", "LIVE", "2026-06-20", "1:00 PM", live)
    assert "1st innings" not in match.score_line
    assert match.chase_line == ""


def test_target_renders_immediately_after_overs():
    live = LiveScore(batting_team="Alpha", score="1-12", overs=2, run_rate="6.00", target=87, required_run_rate="4.17", runs_needed=75, balls_remaining=108, chase_metrics_confident=True)
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "T20", "LIVE", "2026-06-19", "6:00 PM", live)
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/?date=2026-06-19").get_data(as_text=True)
    assert "Target 87" in body
    assert 'class="brief-target">Tar 87' in body
    assert "Alpha" in body and "RR=6.00" in body
    assert body.index("(2)") < body.rindex("Target 87") < body.index("Need 75 off 108") < body.index("RRReq=4.17")


def test_two_day_card_keeps_previous_innings_total_beneath_toss():
    live = LiveScore(
        batting_team="Waratah Warriors", score="0-0", overs="0.2", run_rate="0.00",
        innings_label="1st innings", previous_innings=InningsSummary("Palmerston", "171", "1st innings"),
    )
    match = Match("id", "", "Waratah Warriors", "Palmerston", "Waratah Warriors", "Round 9", "Two Day", "LIVE", "2026-06-20", "11:00 AM", live)
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/").get_data(as_text=True)
    assert "Palmerston 1st innings 171" in body
    assert body.index("Waratah Warriors</span>") < body.index("Palmerston 1st innings 171")


def test_dashboard_hides_internal_fields():
    match = Match("secret-id", "https://secret.test", "Alpha", "Beta", "Beta", "Round 1", "T20", "LIVE", "2026-06-19", "6:00 PM", LiveScore("Beta", "1-37", "9.4", "3.83"))
    class FakeService:
        def matches_for_date(self, *args): return [match]
    client = create_app(FakeService()).test_client()
    body = client.get("/?date=2026-06-19").get_data(as_text=True)
    assert "Alpha" in body and "1-37" in body
    assert "Current batters" not in body and "Current / recent bowlers" not in body
    assert "secret-id" not in body and "https://secret.test" not in body


def test_dashboard_hides_empty_overs_brackets_before_play_starts():
    match = Match(
        "id", "", "Alpha", "Beta", "", "Round 1", "T20", "LIVE",
        "2026-06-19", "6:00 PM", LiveScore("Alpha", "0-0", "", ""),
    )
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/?date=2026-06-19").get_data(as_text=True)
    assert "0-0" in body
    assert "<em>()</em>" not in body


def test_dashboard_adds_grade_dividers_when_grade_changes():
    a_grade = Match(
        "a", "", "Alpha", "Beta", "", "Round 1", "One Day", "LIVE",
        "2026-07-04", "1:00 PM", LiveScore("Alpha", "1-37", "9.4", "3.83"),
        competition_name="A Grade",
    )
    b_grade = Match(
        "b", "", "Gamma", "Delta", "", "Round 1", "One Day", "LIVE",
        "2026-07-04", "1:00 PM", LiveScore("Gamma", "2-50", "12", "4.17"),
        competition_name="B Grade",
    )
    class FakeService:
        def matches_for_date(self, *args): return [a_grade, b_grade]
    body = create_app(FakeService()).test_client().get("/?date=2026-07-04").get_data(as_text=True)
    assert body.count('class="grade-divider"') == 2
    assert body.index("A Grade") < body.index("Alpha")
    assert body.index("B Grade") < body.index("Gamma")


def test_dashboard_setup_link_reflects_saved_feed_state(tmp_path, monkeypatch):
    monkeypatch.delenv("CARNIVAL_GRADE_ID", raising=False)
    class FakeService:
        def matches_for_date(self, *args): return []
        def matches_for_grades(self, *args): return []
    empty_store = FavouriteStore(tmp_path / "empty.json")
    empty_body = create_app(FakeService(), favourite_store=empty_store).test_client().get("/").get_data(as_text=True)
    assert "Set up feed" in empty_body and "Edit Feed" not in empty_body

    saved_store = FavouriteStore(tmp_path / "saved.json")
    saved_store.save("11111111-1111-1111-1111-111111111111", "A Grade", "Darwin")
    saved_body = create_app(FakeService(), favourite_store=saved_store).test_client().get("/").get_data(as_text=True)
    assert "Edit Feed" in saved_body and "Set up feed" not in saved_body


def test_toss_line_shows_inferred_batted_or_bowled_choice():
    detail = {
        "teams": [
            {"id": "a", "displayName": "Alpha", "wonToss": True},
            {"id": "b", "displayName": "Beta"},
        ],
        "innings": [{"battingTeamId": "b", "inningsOrder": 1}],
        "matchSummary": {},
    }
    source = PlayCricketPublicSource()
    assert source._toss_winner(detail) == "Alpha"
    assert source._toss_decision(detail, "Alpha") == "bowled"
    match = Match("id", "", "Alpha", "Beta", "Alpha", "Round 1", "T20", "LIVE", "2026-06-19", "6:00 PM", LiveScore("Beta", "1-37", "9.4", "3.83"), toss_decision="bowled")
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/?date=2026-06-19").get_data(as_text=True)
    assert "(toss Alpha, bowled)" in body


def test_display_mode_selector_and_local_persistence_are_present():
    live = LiveScore(
        batting_team="Alpha", score="1-37", overs="9.4", run_rate="3.83",
        current_batters=[Batter("Current One", 20, 25), Batter("Current Two", 10, 15)],
        dismissed_batters=[Batter("Dismissed One", 7, 8)],
        bowlers=[Bowler("Current Bowler", 1, 12, 3, True), Bowler("Recent Bowler", 0, 8, 2), Bowler("Best Other", 2, 10, 3)],
    )
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "T20", "LIVE", "2026-06-20", "1:00 PM", live)
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/").get_data(as_text=True)
    assert all(f'value="{mode}"' in body for mode in ("brief", "standard", "detailed"))
    assert "current-player-section" in body and "best-section" in body
    root = Path(__file__).parents[1]
    script = (root / "static" / "display-mode.js").read_text()
    styles = (root / "static" / "display-mode.css").read_text()
    assert "carnivalLive.displayMode" in script
    assert 'data-display-mode="brief"' in styles and 'data-display-mode="standard"' in styles


def test_pwa_manifest_metadata_and_service_worker_are_present():
    class FakeService:
        def matches_for_date(self, *args): return []
    client = create_app(FakeService()).test_client()
    dashboard = client.get("/").get_data(as_text=True)
    setup = client.get("/setup").get_data(as_text=True)
    assert 'rel="manifest"' in dashboard and 'manifest.webmanifest' in dashboard
    assert 'apple-mobile-web-app-capable' in dashboard
    assert 'pwa.js' in dashboard
    assert 'rel="manifest"' in setup and 'pwa.js' in setup

    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json["display"] == "standalone"
    assert manifest.json["start_url"] == "/"

    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert b"carnival-live-v1" in worker.data


def test_match_exposes_flat_source_independent_display_contract():
    live = LiveScore(batting_team="Alpha", score="1-37", overs="9.4", run_rate="3.83", target=80, required_run_rate="4.30", runs_needed=43, balls_remaining=60)
    match = Match("id", "url", "Alpha", "Beta", "", "Round 1", "T20", "LIVE", "2026-06-20", "1:00 PM", live, competition_name="Division 1")
    assert (match.competition_name, match.round, match.batting_team, match.score) == ("Division 1", "Round 1", "Alpha", "1-37")
    assert (match.target, match.runs_required, match.required_rate) == (80, 43, "4.30")
    assert match.display_date == "20-Jun-26"


def test_dashboard_uses_short_display_date():
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "T20", "LIVE", "2026-07-04", "1:00 PM", LiveScore("Alpha", "1-37", "9.4", "3.83"))
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/?date=2026-07-04").get_data(as_text=True)
    assert "04-Jul-26 1:00 PM" in body
    assert "2026-07-04 1:00 PM" not in body


def test_service_keeps_completed_but_hides_upcoming_and_other_dates():
    def match(status, date="2026-06-19"):
        return Match(status, "", "Alpha", "Beta", "", "Round 1", "T20", status, date, "6:00 PM")
    class FakeSource:
        def get_matches(self, *args):
            return [match("COMPLETED"), match("LIVE"), match("UPCOMING"), match("FORFEITED"), match("LIVE", "2026-06-20")]
        def add_scorecard(self, item):
            return item
    visible = MatchService(FakeSource()).matches_for_date("grade", "2026-06-19", "Australia/Darwin")
    assert [item.status for item in visible] == ["LIVE", "COMPLETED", "FORFEITED"]


def test_service_keeps_carried_two_day_matches_from_previous_start_date():
    carried_two_day = Match("two-day", "", "Alpha", "Beta", "", "Round 1", "Two Day", "STUMPS", "2026-06-20", "11:00 AM")
    carried_two_day.schedule_dates = ["2026-06-20", "2026-06-27"]
    old_completed = Match("done", "", "Alpha", "Beta", "", "Round 1", "Two Day", "COMPLETED", "2026-06-20", "11:00 AM")
    old_completed.schedule_dates = ["2026-06-20", "2026-06-27"]
    older_completed = Match("older", "", "Alpha", "Beta", "", "Round 0", "Two Day", "COMPLETED", "2026-06-06", "11:00 AM")
    older_completed.schedule_dates = ["2026-06-06", "2026-06-13"]
    same_day_live = Match("today", "", "Alpha", "Beta", "", "Round 2", "One Day", "LIVE", "2026-06-27", "1:00 PM")
    class FakeSource:
        def get_matches(self, *args):
            return [older_completed, carried_two_day, old_completed, same_day_live]
        def add_scorecard(self, item):
            return item
    visible = MatchService(FakeSource()).matches_for_date("grade", "2026-06-27", "Australia/Darwin")
    assert [item.match_id for item in visible] == ["two-day", "today", "done"]


def test_service_does_not_keep_two_day_matches_after_scheduled_dates():
    completed_last_round = Match("done", "", "Alpha", "Beta", "", "Round 1", "Two Day", "COMPLETED", "2026-06-20", "11:00 AM")
    completed_last_round.schedule_dates = ["2026-06-20", "2026-06-27"]
    today_live = Match("today", "", "Alpha", "Beta", "", "Round 2", "One Day", "LIVE", "2026-07-04", "1:00 PM")
    class FakeSource:
        def get_matches(self, *args):
            return [completed_last_round, today_live]
        def add_scorecard(self, item):
            return item
    visible = MatchService(FakeSource()).matches_for_date("grade", "2026-07-04", "Australia/Darwin")
    assert [item.match_id for item in visible] == ["today"]


def test_multi_grade_view_keeps_only_selected_club_and_deduplicates_matches():
    palmerston_two_day = Match("p-b", "", "Palmerston B", "Waratah B", "", "Round 9", "Two Day", "LIVE", "2026-06-20", "12:30 PM")
    palmerston_one_day = Match("p-c", "", "Palmerston C", "Nightcliff C", "", "Round 10", "One Day", "LIVE", "2026-06-20", "1:00 PM")
    unrelated = Match("other", "", "Darwin C", "Nightcliff C", "", "Round 10", "One Day", "LIVE", "2026-06-20", "1:00 PM")
    class FakeSource:
        def get_matches(self, grade_id, *_):
            return [palmerston_two_day, unrelated] if grade_id == "grade-b" else [palmerston_one_day, unrelated]
        def add_scorecard(self, match): return match
    matches = MatchService(FakeSource()).matches_for_grades(
        ["grade-b", "grade-c"], "2026-06-20", "Australia/Darwin", "Palmerston",
        {"grade-b": "B Grade (Sponsor)", "grade-c": "A Grade (Sponsor)"},
    )
    assert [match.match_id for match in matches] == ["p-c", "p-b"]
    assert {match.match_type for match in matches} == {"Two Day", "One Day"}
    assert [match.grade_label for match in matches] == ["A Grade", "B Grade"]


def test_multi_grade_club_filter_ignores_cricket_club_suffix():
    palmerston = Match("p-c", "", "Palmerston C White", "Nightcliff C", "", "Round 10", "One Day", "LIVE", "2026-07-04", "1:00 PM")
    unrelated = Match("other", "", "Darwin C", "PINT C Green", "", "Round 10", "One Day", "LIVE", "2026-07-04", "1:00 PM")
    class FakeSource:
        def get_matches(self, *_): return [palmerston, unrelated]
        def add_scorecard(self, match): return match
    matches = MatchService(FakeSource()).matches_for_grades(
        ["grade-c"], "2026-07-04", "Australia/Darwin", "Palmerston Cricket Club", {"grade-c": "C Grade"},
    )
    assert [match.match_id for match in matches] == ["p-c"]


def test_multi_grade_club_filter_accepts_multiple_clubs():
    palmerston = Match("p-c", "", "Palmerston C White", "Nightcliff C", "", "Round 10", "One Day", "LIVE", "2026-07-04", "1:00 PM")
    pint = Match("pint-c", "", "Darwin C", "PINT C Green", "", "Round 10", "One Day", "LIVE", "2026-07-04", "1:00 PM")
    unrelated = Match("other", "", "Darwin C", "Nightcliff C", "", "Round 10", "One Day", "LIVE", "2026-07-04", "1:00 PM")
    class FakeSource:
        def get_matches(self, *_): return [palmerston, pint, unrelated]
        def add_scorecard(self, match): return match
    matches = MatchService(FakeSource()).matches_for_grades(
        ["grade-c"], "2026-07-04", "Australia/Darwin",
        ["Palmerston Cricket Club", "PINT Cricket Club"], {"grade-c": "C Grade"},
    )
    assert [match.match_id for match in matches] == ["p-c", "pint-c"]


def test_dashboard_routes_multi_grade_club_view():
    class FakeService:
        def matches_for_grades(self, grade_ids, date, timezone, club, grade_names):
            assert grade_ids == ["b23c4063-1f78-4850-a105-e827a4fddf6f", "2e5e9b21-a9fa-45c6-a5af-a468ae8193a9"]
            assert club == "Palmerston"
            return []
    url = "/?grade_ids=b23c4063-1f78-4850-a105-e827a4fddf6f,2e5e9b21-a9fa-45c6-a5af-a468ae8193a9&club=Palmerston&date=2026-06-20"
    assert create_app(FakeService()).test_client().get(url).status_code == 200


def test_forfeit_result_gets_explicit_final_card():
    detail = {
        "status": "COMPLETED", "innings": [],
        "teams": [{"id": "a", "displayName": "Alpha"}, {"id": "b", "displayName": "Beta"}],
        "matchSummary": {"resultText": "Alpha won by forfeit", "teams": [
            {"id": "a", "displayName": "Alpha", "isWinner": True, "scoreText": "0-0"},
            {"id": "b", "displayName": "Beta", "isWinner": False, "scoreText": "0-0"},
        ]},
    }
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "One Day", "COMPLETED", "2026-06-20", "1:00 PM")
    class Source(PlayCricketPublicSource):
        def _get(self, *args, **kwargs): return detail
    Source().add_scorecard(match)
    assert match.is_forfeit and match.result_winner == "Alpha" and match.result_loser == "Beta"
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/").get_data(as_text=True)
    assert "Alpha <span>def</span> Beta <span>by forfeit</span>" in body and "FORFEIT" in body


def test_final_card_shows_winner_margin_and_both_team_summaries():
    summaries = [
        TeamPerformance("Alpha", "2-100", [Batter("A One", 50, 30)], [Bowler("A Bowl", 2, 10, 4)], "20"),
        TeamPerformance("Beta", "8-90", [Batter("B One", 40, 35)], [Bowler("B Bowl", 3, 20, 4)], "20"),
    ]
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "T20", "COMPLETED", "2026-06-19", "6:00 PM", is_final=True, result_winner="Alpha", result_loser="Beta", result_text="Alpha won by 10 runs", result_type="WON_OUTRIGHT_WON_FIRST_INNINGS", performances=summaries)
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/?date=2026-06-19").get_data(as_text=True)
    assert "Alpha <span>def</span> Beta <span>by 10 runs</span>" in body
    assert "outright" not in body
    assert all(name in body for name in ["A One", "A Bowl", "B One", "B Bowl"])
    assert "2-100 (20)" in body and "8-90 (20)" in body


def test_final_badge_shows_first_innings_result():
    match = Match(
        "id", "", "Alpha", "Beta", "", "Round 1", "Two Day", "COMPLETED", "2026-06-19", "6:00 PM",
        is_final=True, result_winner="Alpha", result_loser="Beta",
        result_text="Alpha won by 2 wickets", result_type="WON_ON_FIRST_INNINGS",
    )
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/?date=2026-06-19").get_data(as_text=True)
    assert "Alpha <span>def</span> Beta <span>on first innings</span> <span>by 2 wickets</span>" in body
    assert "FIRST INNINGS" not in body


def test_two_day_final_title_shows_outright_qualifier():
    match = Match(
        "id", "", "Alpha", "Beta", "", "Round 1", "Two Day", "COMPLETED", "2026-06-19", "6:00 PM",
        is_final=True, result_winner="Alpha", result_loser="Beta",
        result_text="Alpha won by 7 wickets", result_type="WON_OUTRIGHT_WON_FIRST_INNINGS",
    )
    class FakeService:
        def matches_for_date(self, *args): return [match]
    body = create_app(FakeService()).test_client().get("/?date=2026-06-19").get_data(as_text=True)
    assert "Alpha <span>def</span> Beta <span>outright</span> <span>by 7 wickets</span>" in body
    assert "OUTRIGHT" not in body


def test_final_bowlers_stay_with_the_innings_they_bowled_in():
    detail = {
        "status": "COMPLETED",
        "teams": [{"id": "a", "displayName": "Alpha"}, {"id": "b", "displayName": "Beta"}],
        "matchSummary": {"teams": [
            {"id": "a", "displayName": "Alpha", "isWinner": True, "scoreText": "2-100"},
            {"id": "b", "displayName": "Beta", "isWinner": False, "scoreText": "8-90"},
        ]},
        "innings": [
            {"battingTeamId": "a", "batting": [{"playerShortName": "A Batter", "runsScored": 50, "ballsFaced": 30}],
             "bowling": [{"playerShortName": "B Bowler", "wicketsTaken": 2, "runsConceded": 20, "oversBowled": 4}]},
            {"battingTeamId": "b", "batting": [{"playerShortName": "B Batter", "runsScored": 40, "ballsFaced": 35}],
             "bowling": [{"playerShortName": "A Bowler", "wicketsTaken": 3, "runsConceded": 15, "oversBowled": 4}]},
        ],
    }
    _, _, summaries = PlayCricketPublicSource().parse_final(detail)
    by_team = {summary.team_name: summary for summary in summaries}
    assert by_team["Alpha"].bowlers[0].name == "B Bowler"
    assert by_team["Beta"].bowlers[0].name == "A Bowler"


def test_two_day_final_ignores_unplayed_end_of_match_innings():
    detail = {
        "status": "COMPLETED",
        "matchType": "Two Day",
        "teams": [{"id": "a", "displayName": "Darwin"}, {"id": "b", "displayName": "Waratah Warriors"}],
        "matchSummary": {"resultText": "Darwin won by 38 runs", "teams": [
            {"id": "a", "displayName": "Darwin", "isWinner": True, "scoreText": "233 & 0-0"},
            {"id": "b", "displayName": "Waratah Warriors", "isWinner": False, "scoreText": "195"},
        ]},
        "innings": [
            {"battingTeamId": "a", "inningsOrder": 1, "inningsCloseType": "All Out", "runsScored": 233, "numberOfWicketsFallen": 10, "oversBowled": 80.5,
             "batting": [{"playerShortName": "Real Darwin Batter", "runsScored": 49, "ballsFaced": 162}],
             "bowling": [{"playerShortName": "Waratah Bowler", "wicketsTaken": 3, "runsConceded": 58, "oversBowled": 17.5}]},
            {"battingTeamId": "b", "inningsOrder": 2, "inningsCloseType": "All Out", "runsScored": 195, "numberOfWicketsFallen": 10, "oversBowled": 69.4,
             "batting": [{"playerShortName": "Waratah Batter", "runsScored": 58, "ballsFaced": 56}],
             "bowling": [{"playerShortName": "Darwin Bowler", "wicketsTaken": 5, "runsConceded": 68, "oversBowled": 29.4}]},
            {"battingTeamId": "a", "inningsOrder": 3, "inningsCloseType": "End of Match", "runsScored": 0, "numberOfWicketsFallen": 0, "oversBowled": 0,
             "batting": [{"playerShortName": "Phantom Opener", "runsScored": 0, "ballsFaced": 0, "dismissalType": "Not Out"}],
             "bowling": []},
        ],
    }
    winner, _, summaries = PlayCricketPublicSource().parse_final(detail)
    by_team = {summary.team_name: summary for summary in summaries}
    assert winner == "Darwin"
    assert by_team["Darwin"].score == "233"
    assert by_team["Darwin"].batters[0].name == "Real Darwin Batter"
    assert by_team["Waratah Warriors"].score == "195"
    assert by_team["Waratah Warriors"].bowlers[0].name == "Darwin Bowler"


def test_setup_search_season_grade_and_favourite_flow(tmp_path):
    class FakeService:
        def matches_for_date(self, *args): return []
    class FakeSetupSource:
        def search_organisations(self, query):
            assert query == "Darwin"
            return [{"organisationGuid": "org-1", "name": "Darwin Competition", "suburb": "Marrara", "stateName": "NT"}]
        def get_organisation_seasons(self, organisation_id):
            return [{"id": "season-1", "name": "Winter 2026", "isCurrentSeason": True}]
        def get_organisation_grades(self, organisation_id, season_id):
            return [{"id": "213859e0-488a-40c6-a642-dcf36df09f04", "name": "Women's Div 1"}]
    store = FavouriteStore(tmp_path / "favourites.json")
    client = create_app(FakeService(), FakeSetupSource(), store).test_client()
    search = client.get("/setup?q=Darwin").get_data(as_text=True)
    assert "Darwin Competition" in search
    organisation = client.get("/setup/organisation/org-1?name=Darwin+Competition").get_data(as_text=True)
    assert "Winter 2026" in organisation and "Women&#39;s Div 1" in organisation
    response = client.post("/setup/favourite", data={
        "grade_id": "https://play.cricket.com.au/grade/213859e0-488a-40c6-a642-dcf36df09f04/womens-div-1",
        "grade_name": "Women's Div 1", "organisation_name": "Darwin Competition",
        "next": "/setup/organisation/org-1?name=Darwin+Competition",
    })
    assert response.status_code == 302
    assert response.headers["Location"] == "/setup/organisation/org-1?name=Darwin+Competition"
    assert store.default_grade_id() == "213859e0-488a-40c6-a642-dcf36df09f04"
    organisation_after_save = client.get("/setup/organisation/org-1?name=Darwin+Competition").get_data(as_text=True)
    assert "Saved favourite" in organisation_after_save and "Go to live scores" in organisation_after_save
    assert "Remove" in organisation_after_save
    removed_from_grades = client.post("/setup/favourite/remove", data={
        "grade_id": "213859e0-488a-40c6-a642-dcf36df09f04",
        "next": "/setup/organisation/org-1?name=Darwin+Competition",
    })
    assert removed_from_grades.headers["Location"] == "/setup/organisation/org-1?name=Darwin+Competition"
    store.save("213859e0-488a-40c6-a642-dcf36df09f04", "Women's Div 1", "Darwin Competition")
    setup = client.get("/setup").get_data(as_text=True)
    assert "Remove" in setup and "View live scores" in setup
    assert "Set up your live feed" in setup
    assert "Your live feed" in setup and "Add to your feed" in setup
    assert "Saved clubs / teams" in setup and "Saved grades" in setup
    assert "all saved favourite grades together" in setup
    assert "Advanced: enter grade URL or ID" not in setup
    assert "Add club/team filter" in setup
    filter_response = client.post("/setup/feed-filter", data={"club_filter": "Palmerston"})
    assert filter_response.status_code == 302
    assert store.club_filter() == "Palmerston"
    client.post("/setup/feed-filter", data={"club_filter": "PINT Cricket Club"})
    assert store.club_filters() == ["Palmerston", "PINT Cricket Club"]
    setup_filtered = client.get("/setup").get_data(as_text=True)
    assert "filtered to Palmerston, PINT Cricket Club" in setup_filtered and "Clear" in setup_filtered
    assert "Clubs / teams" in setup_filtered
    assert "Palmerston" in setup_filtered and "PINT Cricket Club" in setup_filtered
    assert "Competitions" in setup_filtered and "Darwin Competition" in setup_filtered
    clear_response = client.post("/setup/feed-filter", data={"club_filter": ""})
    assert clear_response.status_code == 302
    assert store.club_filter() == ""
    removed = client.post("/setup/favourite/remove", data={"grade_id": "213859e0-488a-40c6-a642-dcf36df09f04"})
    assert removed.status_code == 302
    assert store.all() == []


def test_setup_summary_shows_club_filter_without_saved_grades(tmp_path):
    class FakeService:
        def matches_for_date(self, *args): return []

    store = FavouriteStore(tmp_path / "favourites.json")
    store.add_club_filter("Darwin Cricket Club")
    body = create_app(FakeService(), favourite_store=store).test_client().get("/setup").get_data(as_text=True)
    assert "Your live feed" in body
    assert "Clubs / teams" in body and "Darwin Cricket Club" in body
    assert "No clubs, competitions or grades saved yet" not in body


def test_setup_grades_sort_into_cricket_order():
    grades = [
        {"name": "Under 11 (McDonald's)"},
        {"name": "C Grade (Raikot Group)"},
        {"name": "Sunday 1"},
        {"name": "A Grade (Gatorade)"},
        {"name": "Premier T20 (Whittles)"},
        {"name": "Women's Div 2 (Arafura Connect)"},
        {"name": "B Grade (DXC Technology)"},
        {"name": "Grade F"},
        {"name": "Grade 2"},
        {"name": "A"},
        {"name": "Under 16 Blue (McDonald's)"},
        {"name": "D Grade (Raikot Group)"},
        {"name": "E Grade (Raikot Group)"},
    ]
    ordered = [grade["name"] for grade in sorted(grades, key=grade_setup_order)]
    assert set(ordered[:2]) == {"A Grade (Gatorade)", "A"}
    assert ordered.index("B Grade (DXC Technology)") < ordered.index("C Grade (Raikot Group)")
    assert ordered.index("Grade 2") < ordered.index("D Grade (Raikot Group)")
    assert ordered.index("Grade F") > ordered.index("E Grade (Raikot Group)")
    assert ordered.index("Premier T20 (Whittles)") < ordered.index("Women's Div 2 (Arafura Connect)")
    assert ordered.index("Sunday 1") < ordered.index("Under 16 Blue (McDonald's)")


def test_setup_favourites_render_in_cricket_grade_order(tmp_path):
    store = FavouriteStore(tmp_path / "favourites.json")
    store.save("44444444-4444-4444-4444-444444444444", "D Grade", "Darwin")
    store.save("22222222-2222-2222-2222-222222222222", "B Grade", "Darwin")
    store.save("33333333-3333-3333-3333-333333333333", "C Grade", "Darwin")
    store.save("11111111-1111-1111-1111-111111111111", "A Grade", "Darwin")
    class FakeService:
        def matches_for_date(self, *args): return []
    body = create_app(FakeService(), favourite_store=store).test_client().get("/setup").get_data(as_text=True)
    assert body.index("A Grade") < body.index("B Grade") < body.index("C Grade") < body.index("D Grade")


def test_match_grade_order_handles_letters_and_numbers_both_ways():
    grade_names = ["Grade C", "A", "2nd Grade", "Grade B", "Grade 1", "D Grade"]
    matches = [
        Match(name, "", "Alpha", "Beta", "", "Round 1", "One Day", "LIVE", "2026-07-04", "1:00 PM", competition_name=name)
        for name in grade_names
    ]
    ordered = [match.grade_label for match in sorted(matches, key=lambda item: item.grade_order)]
    assert ordered == ["A", "Grade 1", "2nd Grade", "Grade B", "Grade C", "D Grade"]


def test_setup_shows_current_season_only_and_guides_club_results(tmp_path):
    class FakeService:
        def matches_for_date(self, *args): return []
    class FakeSetupSource:
        def search_organisations(self, query): return []
        def get_organisation_seasons(self, organisation_id):
            return [
                {"id": "old", "name": "Winter 2025", "isCurrentSeason": False},
                {"id": "current", "name": "Winter 2026", "isCurrentSeason": True},
            ]
        def get_organisation_grades(self, organisation_id, season_id):
            assert season_id == "current"
            return []
        def get_organisation_teams(self, organisation_id, season_id):
            return []
    client = create_app(FakeService(), FakeSetupSource(), FavouriteStore(tmp_path / "favourites.json")).test_client()
    body = client.get("/setup/organisation/org-1?name=Palmerston+Cricket+Club").get_data(as_text=True)
    assert "Winter 2026" in body and "Winter 2025" not in body
    assert "grades are often listed under the association" in body
    assert "Save this club/team as your filter" in body
    response = client.post("/setup/feed-filter", data={"club_filter": "Palmerston Cricket Club"})
    assert response.status_code == 302


def test_setup_club_page_shows_team_grades_and_sets_filter(tmp_path):
    grade_id = "11111111-1111-1111-1111-111111111111"
    class FakeService:
        def matches_for_date(self, *args): return []
    class FakeSetupSource:
        def search_organisations(self, query): return []
        def get_organisation_seasons(self, organisation_id):
            return [{"id": "current", "name": "Winter 2026", "isCurrentSeason": True}]
        def get_organisation_grades(self, organisation_id, season_id):
            return []
        def get_organisation_teams(self, organisation_id, season_id):
            return [
                {"id": "team-1", "name": "A Grade", "grade": {
                    "id": grade_id, "name": "A Grade",
                    "owningOrganisation": {"name": "Darwin & Districts Cricket Competition"},
                }},
                {"id": "team-2", "name": "A Grade White", "grade": {
                    "id": grade_id, "name": "A Grade",
                    "owningOrganisation": {"name": "Darwin & Districts Cricket Competition"},
                }},
            ]
    store = FavouriteStore(tmp_path / "favourites.json")
    client = create_app(FakeService(), FakeSetupSource(), store).test_client()
    body = client.get("/setup/organisation/org-1?name=Darwin+Cricket+Club").get_data(as_text=True)
    assert "Club teams found" in body
    assert "Darwin &amp; Districts Cricket Competition" in body
    assert "A Grade, A Grade White" in body
    response = client.post("/setup/favourite", data={
        "grade_id": grade_id,
        "grade_name": "A Grade",
        "organisation_name": "Darwin & Districts Cricket Competition",
        "club_filter": "Darwin Cricket Club",
    })
    assert response.status_code == 302
    assert store.default_grade_id() == grade_id
    assert store.club_filters() == ["Darwin Cricket Club"]


def test_club_team_grade_options_collapses_duplicate_teams_by_grade():
    grade_id = "11111111-1111-1111-1111-111111111111"
    options = club_team_grade_options([
        {"name": "C Grade", "grade": {"id": grade_id, "name": "C Grade", "owningOrganisation": {"name": "Assoc"}}},
        {"name": "C Grade White", "grade": {"id": grade_id, "name": "C Grade", "owningOrganisation": {"name": "Assoc"}}},
        {"name": "Bad", "grade": {"id": "bad", "name": "Bad"}},
    ])
    assert options == [{
        "id": grade_id,
        "name": "C Grade",
        "owning_organisation": "Assoc",
        "teams": "C Grade, C Grade White",
    }]


def test_current_seasons_falls_back_when_no_current_flag_exists():
    seasons = [{"id": "one", "name": "Season One"}, {"id": "two", "name": "Season Two"}]
    assert current_seasons_only(seasons) == seasons


def test_dashboard_uses_all_saved_favourites_when_no_grade_is_requested(tmp_path, monkeypatch):
    monkeypatch.delenv("CARNIVAL_GRADE_ID", raising=False)
    store = FavouriteStore(tmp_path / "favourites.json")
    store.save("11111111-1111-1111-1111-111111111111", "A Grade", "Darwin")
    store.save("22222222-2222-2222-2222-222222222222", "B Grade", "Darwin")
    store.set_club_filter("Palmerston")
    class FakeService:
        def matches_for_grades(self, grade_ids, date, timezone, club, grade_names):
            assert grade_ids == [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ]
            assert club == ["Palmerston"]
            assert grade_names["11111111-1111-1111-1111-111111111111"] == "A Grade"
            return []
        def matches_for_date(self, *args):
            raise AssertionError("single-grade dashboard should not be used")
    assert create_app(FakeService(), favourite_store=store).test_client().get("/").status_code == 200


def test_favourite_grade_selection_ignores_duplicates_and_bad_ids():
    ids, names = favourite_grade_selection([
        {"grade_id": "bad", "grade_name": "Bad"},
        {"grade_id": "11111111-1111-1111-1111-111111111111", "grade_name": "A Grade"},
        {"grade_id": "11111111-1111-1111-1111-111111111111", "grade_name": "Duplicate"},
    ])
    assert ids == ["11111111-1111-1111-1111-111111111111"]
    assert names == {"11111111-1111-1111-1111-111111111111": "A Grade"}


def test_two_day_previous_innings_line_includes_lead_or_chase_context():
    live = LiveScore(
        batting_team="Beta", score="2-80", overs=30, run_rate="2.67", runs=80,
        previous_innings=InningsSummary("Alpha", "127", "1st innings", 127),
        two_day_context="Beta trail by 47",
    )
    match = Match("id", "", "Alpha", "Beta", "", "Round 1", "Two Day", "LIVE", "2026-06-27", "1:00 PM", live)
    assert match.previous_innings_line == "Alpha 1st innings 127 · Beta trail by 47"


def test_two_day_parser_uses_aggregate_totals_for_third_innings_lead():
    detail = {
        "matchType": "Two Day",
        "teams": [{"id": "a", "displayName": "Alpha"}, {"id": "b", "displayName": "Beta"}],
        "innings": [
            {"battingTeamId": "a", "inningsOrder": 1, "inningsCloseType": "ALL OUT", "runsScored": 100, "numberOfWicketsFallen": 10, "oversBowled": 30, "batting": [], "bowling": []},
            {"battingTeamId": "b", "inningsOrder": 2, "inningsCloseType": "ALL OUT", "runsScored": 80, "numberOfWicketsFallen": 10, "oversBowled": 30, "batting": [], "bowling": []},
            {"battingTeamId": "a", "inningsOrder": 3, "inningsCloseType": "IN PROGRESS", "runsScored": 30, "numberOfWicketsFallen": 1, "oversBowled": 10, "batting": [], "bowling": []},
        ],
    }
    live = PlayCricketPublicSource().parse_scorecard(detail, MatchFormat.from_source("Two Day"))
    assert live.two_day_context == "Alpha lead by 50"


def test_two_day_parser_shows_fourth_innings_runs_needed():
    detail = {
        "matchType": "Two Day",
        "teams": [{"id": "a", "displayName": "Alpha"}, {"id": "b", "displayName": "Beta"}],
        "innings": [
            {"battingTeamId": "a", "inningsOrder": 1, "inningsCloseType": "ALL OUT", "runsScored": 100, "numberOfWicketsFallen": 10, "oversBowled": 30, "batting": [], "bowling": []},
            {"battingTeamId": "b", "inningsOrder": 2, "inningsCloseType": "ALL OUT", "runsScored": 80, "numberOfWicketsFallen": 10, "oversBowled": 30, "batting": [], "bowling": []},
            {"battingTeamId": "a", "inningsOrder": 3, "inningsCloseType": "ALL OUT", "runsScored": 50, "numberOfWicketsFallen": 10, "oversBowled": 20, "batting": [], "bowling": []},
            {"battingTeamId": "b", "inningsOrder": 4, "inningsCloseType": "IN PROGRESS", "runsScored": 10, "numberOfWicketsFallen": 0, "oversBowled": 5, "batting": [], "bowling": []},
        ],
    }
    live = PlayCricketPublicSource().parse_scorecard(detail, MatchFormat.from_source("Two Day"))
    assert live.target == 71
    assert live.two_day_context == "Beta need 61"


def test_two_day_parser_prefers_source_lead_trail_text_over_calculated_need():
    detail = {
        "matchType": "Two Day",
        "matchSummary": {"resultText": "Beta trails by 56", "teams": [
            {"id": "a", "displayName": "Alpha", "scoreText": "100 & 50"},
            {"id": "b", "displayName": "Beta", "scoreText": "80 & 4-14"},
        ]},
        "teams": [{"id": "a", "displayName": "Alpha"}, {"id": "b", "displayName": "Beta"}],
        "innings": [
            {"battingTeamId": "a", "inningsOrder": 1, "inningsCloseType": "ALL OUT", "runsScored": 100, "numberOfWicketsFallen": 10, "oversBowled": 30, "batting": [], "bowling": []},
            {"battingTeamId": "b", "inningsOrder": 2, "inningsCloseType": "ALL OUT", "runsScored": 80, "numberOfWicketsFallen": 10, "oversBowled": 30, "batting": [], "bowling": []},
            {"battingTeamId": "a", "inningsOrder": 3, "inningsCloseType": "ALL OUT", "runsScored": 50, "numberOfWicketsFallen": 10, "oversBowled": 20, "batting": [], "bowling": []},
            {"battingTeamId": "b", "inningsOrder": 4, "inningsCloseType": "IN PROGRESS", "runsScored": 14, "numberOfWicketsFallen": 4, "oversBowled": 5, "batting": [], "bowling": []},
        ],
    }
    live = PlayCricketPublicSource().parse_scorecard(detail, MatchFormat.from_source("Two Day"))
    assert live.target == 71
    assert live.two_day_context == "Beta trails by 56"
