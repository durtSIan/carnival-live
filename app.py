from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, redirect, render_template, request, url_for

from data_sources import PlayCricketPublicSource
from favourites import FavouriteStore
from services import MatchService


DEFAULT_GRADE_ID = "213859e0-488a-40c6-a642-dcf36df09f04"
DEFAULT_TIMEZONE = "Australia/Darwin"


GRADE_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

def create_app(service: MatchService | None = None, setup_source=None, favourite_store: FavouriteStore | None = None) -> Flask:
    app = Flask(__name__)
    source = setup_source or PlayCricketPublicSource()
    match_service = service or MatchService(source)
    favourites = favourite_store or FavouriteStore(app.instance_path + "/favourites.json")

    @app.get("/")
    def dashboard():
        timezone_name = request.args.get("timezone", os.getenv("CARNIVAL_TIMEZONE", DEFAULT_TIMEZONE))
        selected_date = request.args.get("date") or datetime.now(ZoneInfo(timezone_name)).date().isoformat()
        grade_id = request.args.get("grade_id") or os.getenv("CARNIVAL_GRADE_ID") or favourites.default_grade_id() or DEFAULT_GRADE_ID
        grade_ids = [value for value in request.args.get("grade_ids", "").split(",") if GRADE_ID_PATTERN.fullmatch(value.strip())][:10]
        grade_labels = [value.strip() for value in request.args.get("grade_labels", "").split(",")][:len(grade_ids)]
        grade_names = dict(zip(grade_ids, grade_labels))
        club_name = request.args.get("club", "").strip()
        error = ""
        try:
            matches = (
                match_service.matches_for_grades(grade_ids, selected_date, timezone_name, club_name, grade_names)
                if grade_ids else match_service.matches_for_date(grade_id, selected_date, timezone_name)
            )
        except Exception as exc:
            app.logger.exception("Could not load live cricket data")
            matches, error = [], "Live scores are temporarily unavailable. Retrying shortly."
        return render_template("dashboard.html", matches=matches, selected_date=selected_date, error=error)

    @app.get("/setup")
    def setup_search():
        query, results, error = request.args.get("q", "").strip(), [], ""
        if len(query) >= 3:
            try: results = source.search_organisations(query)
            except Exception:
                app.logger.exception("Play Cricket organisation search failed")
                error = "Search is temporarily unavailable. You can still use advanced grade entry."
        return render_template("setup_search.html", query=query, results=results, favourites=favourites.all(), error=error)

    @app.get("/setup/organisation/<organisation_id>")
    def setup_organisation(organisation_id: str):
        name, selected, error = request.args.get("name", "Organisation"), request.args.get("season", ""), ""
        try:
            seasons = source.get_organisation_seasons(organisation_id)
            if not selected and seasons:
                selected = str(next((x for x in seasons if x.get("isCurrentSeason")), seasons[0]).get("id") or "")
            grades = source.get_organisation_grades(organisation_id, selected) if selected else []
        except Exception:
            app.logger.exception("Could not load organisation seasons/grades")
            seasons, grades, error = [], [], "Could not load seasons and grades for this organisation."
        return render_template("setup_organisation.html", organisation_id=organisation_id, organisation_name=name, seasons=seasons, selected_season=selected, grades=grades, error=error)

    @app.post("/setup/favourite")
    def save_favourite():
        found = GRADE_ID_PATTERN.search(request.form.get("grade_id", "").strip())
        if not found: return redirect(url_for("setup_search", manual_error="Enter a valid Play Cricket grade ID or URL."))
        grade_id = found.group(0)
        favourites.save(grade_id, request.form.get("grade_name", "").strip() or grade_id, request.form.get("organisation_name", "").strip())
        return redirect(url_for("dashboard", grade_id=grade_id))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
