from __future__ import annotations
import json
from pathlib import Path
from threading import Lock

class FavouriteStore:
    def __init__(self, path: str | Path): self.path, self._lock = Path(path), Lock()
    def all(self) -> list[dict[str, str]]:
        if not self.path.exists(): return []
        try: data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return []
        return data if isinstance(data, list) else []
    def save(self, grade_id: str, grade_name: str, organisation_name: str = "") -> None:
        item = {"grade_id": grade_id, "grade_name": grade_name or grade_id, "organisation_name": organisation_name}
        with self._lock:
            data = [x for x in self.all() if x.get("grade_id") != grade_id]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([item, *data], indent=2), encoding="utf-8")
    def default_grade_id(self) -> str:
        data = self.all()
        return str(data[0].get("grade_id") or "") if data else ""
