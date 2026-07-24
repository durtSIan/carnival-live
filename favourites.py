from __future__ import annotations
import json
from pathlib import Path
from threading import Lock


class FavouriteStore:
    def __init__(self, path: str | Path): self.path, self._lock = Path(path), Lock()
    def _read(self) -> dict:
        if not self.path.exists(): return {"grades": [], "club_filters": []}
        try: data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return {"grades": [], "club_filters": []}
        if isinstance(data, list):
            return {"grades": data, "club_filters": []}
        if not isinstance(data, dict):
            return {"grades": [], "club_filters": []}
        if "club_filters" not in data:
            club_filter = str(data.get("club_filter") or "").strip()
            data["club_filters"] = [club_filter] if club_filter else []
        return data
    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    def all(self) -> list[dict[str, str]]:
        data = self._read()
        grades = data.get("grades")
        return grades if isinstance(grades, list) else []
    def club_filter(self) -> str:
        return ", ".join(self.club_filters())
    def club_filters(self) -> list[str]:
        filters = self._read().get("club_filters")
        if not isinstance(filters, list):
            return []
        return [str(item).strip() for item in filters if str(item).strip()]
    def save(self, grade_id: str, grade_name: str, organisation_name: str = "") -> None:
        item = {"grade_id": grade_id, "grade_name": grade_name or grade_id, "organisation_name": organisation_name}
        with self._lock:
            data = self._read()
            grades = [x for x in self.all() if x.get("grade_id") != grade_id]
            data["grades"] = [item, *grades]
            self._write(data)
    def remove(self, grade_id: str) -> None:
        with self._lock:
            data = self._read()
            data["grades"] = [x for x in self.all() if x.get("grade_id") != grade_id]
            self._write(data)
    def set_club_filter(self, club_filter: str) -> None:
        with self._lock:
            data = self._read()
            values = [item.strip() for item in club_filter.split(",") if item.strip()]
            data["club_filters"] = list(dict.fromkeys(values))
            data.pop("club_filter", None)
            self._write(data)
    def add_club_filter(self, club_filter: str) -> None:
        value = club_filter.strip()
        if not value:
            return
        with self._lock:
            data = self._read()
            filters = self.club_filters()
            if value not in filters:
                filters.append(value)
            data["club_filters"] = filters
            data.pop("club_filter", None)
            self._write(data)
    def remove_club_filter(self, club_filter: str) -> None:
        value = club_filter.strip()
        with self._lock:
            data = self._read()
            data["club_filters"] = [item for item in self.club_filters() if item != value]
            data.pop("club_filter", None)
            self._write(data)
    def default_grade_id(self) -> str:
        data = self.all()
        return str(data[0].get("grade_id") or "") if data else ""


class SessionFavouriteStore(FavouriteStore):
    """Store one anonymous user's feed in Flask's signed session cookie."""

    def __init__(self, session_key: str = "carnival_live_feed"):
        self.session_key = session_key
        self._lock = Lock()

    def _read(self) -> dict:
        from flask import session

        data = session.get(self.session_key)
        if not isinstance(data, dict):
            return {"grades": [], "club_filters": []}
        grades = data.get("grades")
        filters = data.get("club_filters")
        return {
            "grades": grades if isinstance(grades, list) else [],
            "club_filters": filters if isinstance(filters, list) else [],
        }

    def _write(self, data: dict) -> None:
        from flask import session

        session[self.session_key] = {
            "grades": data.get("grades") if isinstance(data.get("grades"), list) else [],
            "club_filters": (
                data.get("club_filters") if isinstance(data.get("club_filters"), list) else []
            ),
        }
        session.permanent = True
        session.modified = True
