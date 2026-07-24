from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, redirect, render_template, request, send_from_directory, url_for

from data_sources import PlayCricketPublicSource
from favourites import FavouriteStore, SessionFavouriteStore
from services import MatchService


DEFAULT_GRADE_ID = "213859e0-488a-40c6-a642-dcf36df09f04"
DEFAULT_TIMEZONE = "Australia/Darwin"


GRADE_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

def grade_setup_order(grade: dict) -> tuple[int, int, str]:
    """Put common cricket grades in a useful selection order."""
    name = str(grade.get("name") or "").strip()
    label = re.sub(r"\s*\([^)]*\)\s*", " ", name.upper()).strip()

    letter = re.search(r"\b(?:GRADE\s+([A-Z])|([A-Z])\s+GRADE)\b", label)
    if letter:
        return (10, ord(letter.group(1) or letter.group(2)) - ord("A"), name)

    number = re.search(r"\b(?:GRADE\s*(\d+)|(\d+)(?:ST|ND|RD|TH)\s+GRADE)\b", label)
    if number:
        return (10, int(number.group(1) or number.group(2)), name)

    division = re.search(r"\bDIV(?:ISION)?\s*(\d+)\b", label)
    if division:
        return (30, int(division.group(1)), name)

    if "PREMIER" in label:
        return (20, 0, name)
    if "CLUB T20" in label:
        return (25, 0, name)
    if "WOMEN" in label:
        return (30, 99, name)

    plain_letter = re.fullmatch(r"[A-Z]", label)
    if plain_letter:
        return (10, ord(label) - ord("A"), name)

    sunday = re.search(r"\bSUNDAY\s*(\d+)\b", label)
    if sunday:
        return (40, int(sunday.group(1)), name)

    junior = re.search(r"\b(?:UNDER|U)\s*(\d+)\b", label)
    if junior:
        return (50, 99 - int(junior.group(1)), name)

    return (90, 0, name)

def current_seasons_only(seasons: list[dict]) -> list[dict]:
    """Prefer the current season in setup; fall back to all seasons if none are flagged."""
    current = [season for season in seasons if season.get("isCurrentSeason")]
    return current or seasons

def club_team_grade_options(teams: list[dict]) -> list[dict[str, str]]:
    """Collapse a club's teams into unique grade feed choices."""
    options: dict[str, dict[str, str | list[str]]] = {}
    for team in teams:
        grade = team.get("grade") or (team.get("grades") or [{}])[0] or {}
        grade_id = str(grade.get("id") or "")
        if not GRADE_ID_PATTERN.fullmatch(grade_id):
            continue
        owner = grade.get("owningOrganisation") or {}
        item = options.setdefault(grade_id, {
            "id": grade_id,
            "name": str(grade.get("name") or team.get("name") or grade_id),
            "owning_organisation": str(owner.get("name") or ""),
            "team_names": [],
        })
        team_name = str(team.get("name") or "").strip()
        if team_name and team_name not in item["team_names"]:
            item["team_names"].append(team_name)
    collapsed = []
    for item in options.values():
        teams_text = ", ".join(item.pop("team_names"))
        item["teams"] = teams_text
        collapsed.append(item)
    return sorted(collapsed, key=lambda item: (item.get("owning_organisation", ""), grade_setup_order(item)))

def favourite_grade_selection(items: list[dict[str, str]]) -> tuple[list[str], dict[str, str]]:
    grade_ids: list[str] = []
    grade_names: dict[str, str] = {}
    for item in sorted_favourite_items(items):
        grade_id = str(item.get("grade_id") or "").strip()
        if not GRADE_ID_PATTERN.fullmatch(grade_id) or grade_id in grade_ids:
            continue
        grade_ids.append(grade_id)
        grade_names[grade_id] = str(item.get("grade_name") or grade_id)
    return grade_ids[:10], grade_names

def sorted_favourite_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(items, key=lambda item: grade_setup_order({"name": item.get("grade_name") or ""}))

def favourite_organisation_names(items: list[dict[str, str]]) -> list[str]:
    """Return each saved competition/association name once, preserving feed order."""
    names: list[str] = []
    for item in items:
        name = str(item.get("organisation_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names

def setup_redirect_target(default: str = "/setup") -> str:
    target = request.form.get("next", "").strip()
    return target if target.startswith("/setup") else default

def create_app(service: MatchService | None = None, setup_source=None, favourite_store: FavouriteStore | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("CARNIVAL_SECRET_KEY", "carnival-live-development-cookie-key"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("CARNIVAL_SECURE_COOKIES", "").lower() in {"1", "true", "yes"},
    )
    source = setup_source or PlayCricketPublicSource()
    match_service = service or MatchService(source)
    favourites = favourite_store or SessionFavouriteStore()

    @app.get("/")
    def dashboard():
        timezone_name = request.args.get("timezone", os.getenv("CARNIVAL_TIMEZONE", DEFAULT_TIMEZONE))
        selected_date = request.args.get("date") or datetime.now(ZoneInfo(timezone_name)).date().isoformat()
        requested_grade_id = request.args.get("grade_id")
        favourite_grade_ids, favourite_grade_names = favourite_grade_selection(favourites.all())
        grade_id = requested_grade_id or os.getenv("CARNIVAL_GRADE_ID") or favourites.default_grade_id() or DEFAULT_GRADE_ID
        grade_ids = [value for value in request.args.get("grade_ids", "").split(",") if GRADE_ID_PATTERN.fullmatch(value.strip())][:10]
        grade_labels = [value.strip() for value in request.args.get("grade_labels", "").split(",")][:len(grade_ids)]
        grade_names = dict(zip(grade_ids, grade_labels))
        using_saved_favourites = False
        if not requested_grade_id and not grade_ids and not os.getenv("CARNIVAL_GRADE_ID") and favourite_grade_ids:
            grade_ids, grade_names = favourite_grade_ids, favourite_grade_names
            using_saved_favourites = True
        requested_club = request.args.get("club", "").strip()
        club_name = requested_club or (favourites.club_filters() if using_saved_favourites else "")
        error = ""
        try:
            matches = (
                match_service.matches_for_grades(grade_ids, selected_date, timezone_name, club_name, grade_names)
                if grade_ids else match_service.matches_for_date(grade_id, selected_date, timezone_name)
            )
        except Exception as exc:
            app.logger.exception("Could not load live cricket data")
            matches, error = [], None
        return render_template(
            "dashboard.html", matches=matches, selected_date=selected_date, error=error,
            has_saved_feed=bool(favourite_grade_ids),
        )

    @app.get("/setup")
    def setup_search():
        query, results, error = request.args.get("q", "").strip(), [], ""
        if len(query) > 20:
            error = "Search names must be 20 characters or fewer."
        elif len(query) >= 3:
            try: results = source.search_organisations(query)
            except Exception:
                app.logger.exception("Play Cricket organisation search failed")
                error = "Search is temporarily unavailable. Please try again shortly."
        favourite_items = sorted_favourite_items(favourites.all())
        return render_template(
            "setup_search.html", query=query, results=results, favourites=favourite_items,
            favourite_organisations=favourite_organisation_names(favourite_items),
            club_filter=favourites.club_filter(), club_filters=favourites.club_filters(), error=error,
        )

    @app.get("/setup/organisation/<organisation_id>")
    def setup_organisation(organisation_id: str):
        name, selected, error = request.args.get("name", "Organisation"), request.args.get("season", ""), ""
        try:
            seasons = current_seasons_only(source.get_organisation_seasons(organisation_id))
            if not selected and seasons:
                selected = str(next((x for x in seasons if x.get("isCurrentSeason")), seasons[0]).get("id") or "")
            if selected and seasons and selected not in {str(x.get("id") or "") for x in seasons}:
                selected = str(seasons[0].get("id") or "")
            grades = sorted(source.get_organisation_grades(organisation_id, selected), key=grade_setup_order) if selected else []
            club_team_grades = club_team_grade_options(source.get_organisation_teams(organisation_id, selected)) if selected and not grades and hasattr(source, "get_organisation_teams") else []
        except Exception:
            app.logger.exception("Could not load organisation seasons/grades")
            seasons, grades, club_team_grades, error = [], [], [], "Could not load seasons and grades for this organisation."
        favourite_items = sorted_favourite_items(favourites.all())
        saved_grade_ids = {str(item.get("grade_id") or "") for item in favourite_items}
        return render_template(
            "setup_organisation.html", organisation_id=organisation_id, organisation_name=name,
            seasons=seasons, selected_season=selected, grades=grades, club_team_grades=club_team_grades, error=error,
            favourites=favourite_items, saved_grade_ids=saved_grade_ids,
            club_filter=favourites.club_filter(), club_filters=favourites.club_filters(),
        )

    @app.post("/setup/favourite")
    def save_favourite():
        found = GRADE_ID_PATTERN.search(request.form.get("grade_id", "").strip())
        if not found: return redirect(url_for("setup_search", manual_error="Enter a valid Play Cricket grade ID or URL."))
        grade_id = found.group(0)
        favourites.save(grade_id, request.form.get("grade_name", "").strip() or grade_id, request.form.get("organisation_name", "").strip())
        club_filter = request.form.get("club_filter", "").strip()
        if club_filter:
            favourites.add_club_filter(club_filter)
        return redirect(setup_redirect_target(url_for("setup_search")))

    @app.post("/setup/favourite/remove")
    def remove_favourite():
        found = GRADE_ID_PATTERN.search(request.form.get("grade_id", "").strip())
        if found:
            favourites.remove(found.group(0))
        return redirect(setup_redirect_target(url_for("setup_search")))

    @app.post("/setup/feed-filter")
    def save_feed_filter():
        club_filter = request.form.get("club_filter", "").strip()
        if club_filter:
            favourites.add_club_filter(club_filter)
        else:
            favourites.set_club_filter("")
        return redirect(setup_redirect_target(url_for("setup_search")))

    @app.post("/setup/feed-filter/remove")
    def remove_feed_filter():
        favourites.remove_club_filter(request.form.get("club_filter", ""))
        return redirect(setup_redirect_target(url_for("setup_search")))

    @app.get("/service-worker.js")
    def service_worker():
        return send_from_directory(app.static_folder, "service-worker.js", mimetype="text/javascript")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
