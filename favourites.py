from __future__ import annotations
import json
from pathlib import Path
from threading import Lock

class FavouriteStore:
    def __init__(self, path: str | Path): self.path, self._lock = Path(path), Lock()
    def _read(self) -> dict:
        if not self.path.exists(): return {"grades": [], "club_filter": ""}
        try: data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return {"grades": [], "club_filter": ""}
        if isinstance(data, list):
            return {"grades": data, "club_filter": ""}
        return data if isinstance(data, dict) else {"grades": [], "club_filter": ""}
    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    def all(self) -> list[dict[str, str]]:
        data = self._read()
        grades = data.get("grades")
        return grades if isinstance(grades, list) else []
    def club_filter(self) -> str:
        return str(self._read().get("club_filter") or "").strip()
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
            data["club_filter"] = club_filter.strip()
            self._write(data)
    def default_grade_id(self) -> str:
        data = self.all()
        return str(data[0].get("grade_id") or "") if data else ""
