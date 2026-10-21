from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from app import create_app
from usage import UsageStore


def test_devices_expire_deduplicate_and_survive_restart(tmp_path):
    now = [datetime(2026, 10, 21, 12, tzinfo=ZoneInfo("Australia/Sydney")).timestamp()]
    path = str(tmp_path / "usage.sqlite3")
    store = UsageStore(path, "secret", clock=lambda: now[0])
    store.heartbeat("a" * 32)
    store.heartbeat("a" * 32)
    store.heartbeat("b" * 32)
    assert (store.snapshot()["active"], store.snapshot()["unique"], store.snapshot()["peak"]) == (2, 2, 2)
    now[0] += 121
    reopened = UsageStore(path, "secret", clock=lambda: now[0])
    assert reopened.snapshot()["active"] == 0
    assert reopened.snapshot()["peak"] == 2
    reopened.heartbeat("a" * 32)
    assert reopened.snapshot()["unique"] == 2
    with reopened.connect() as db:
        assert db.execute("SELECT device FROM viewers").fetchone()[0] != "a" * 32
    now[0] += 86400
    reopened.heartbeat("a" * 32)
    assert reopened.snapshot()["unique"] == 1
    now[0] += 3 * 86400
    reopened.heartbeat("c" * 32)
    with reopened.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM viewers").fetchone()[0] == 1
    assert any(row[2] == 2 for row in reopened.snapshot()["history"])


def test_concurrent_heartbeats_keep_correct_peak(tmp_path):
    store = UsageStore(str(tmp_path / "usage.sqlite3"), "secret")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(store.heartbeat, [f"{i:032x}" for i in range(20)]))
    stats = store.snapshot()
    assert (stats["active"], stats["unique"], stats["peak"]) == (20, 20, 20)


class EmptyService:
    def matches_for_date(self, *args):
        return []


def configure(monkeypatch, tmp_path):
    monkeypatch.setenv("CARNIVAL_ADMIN_PASSWORD", "test-private-password")
    monkeypatch.setenv("CARNIVAL_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("CARNIVAL_SECRET_KEY", "test-secret")
    return create_app(EmptyService())


def test_private_page_and_validated_heartbeats(monkeypatch, tmp_path):
    app = configure(monkeypatch, tmp_path)
    client = app.test_client()
    assert client.get("/admin/usage").status_code == 401
    assert client.get("/admin/usage", auth=("admin", "wrong")).status_code == 401
    result = client.get("/admin/usage", auth=("admin", "test-private-password"))
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert client.post("/usage/heartbeat", json={"device": "a" * 32}).status_code == 204
    assert client.post("/usage/heartbeat", json={"device": "a" * 32}).status_code == 204
    for body in ({}, [], {"device": "invalid"}, {"device": 12}):
        assert client.post("/usage/heartbeat", json=body).status_code == 400
    assert client.post("/usage/heartbeat", json={"device": "b" * 32}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/usage/heartbeat", json={"device": "b" * 300}).status_code == 400
    client.get("/")
    store = app.extensions["usage_store"]
    stats = store.snapshot()
    assert stats["unique"] == 1
    assert stats["requests"] == 1  # Admin and heartbeat traffic do not inflate page health.
    assert "usage.js" in client.get("/").text
    original = store.record_response
    def unavailable(*args):
        raise OSError("disk unavailable")
    store.record_response = unavailable
    assert client.get("/").status_code == 200
    store.record_response = original


def test_monitor_disabled_until_configured(monkeypatch):
    monkeypatch.delenv("CARNIVAL_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("CARNIVAL_USAGE_DB", raising=False)
    client = create_app(EmptyService()).test_client()
    assert "usage.js" not in client.get("/").text
    assert client.get("/admin/usage").status_code == 503
    assert client.post("/usage/heartbeat", json={"device": "a" * 32}).status_code == 503


def test_feed_failures_count_even_when_page_returns_200(monkeypatch, tmp_path):
    app = configure(monkeypatch, tmp_path)
    class BrokenService:
        def matches_for_date(self, *args):
            raise RuntimeError("feed unavailable")
    client = create_app(BrokenService()).test_client()
    assert client.get("/").status_code == 200
    assert app.extensions["usage_store"].snapshot()["errors"] == 1


def test_invalid_storage_does_not_break_scores(monkeypatch, tmp_path):
    monkeypatch.setenv("CARNIVAL_ADMIN_PASSWORD", "private-password")
    monkeypatch.setenv("CARNIVAL_USAGE_DB", str(tmp_path))  # A directory, not a database file.
    client = create_app(EmptyService()).test_client()
    assert client.get("/").status_code == 200
    assert "usage.js" not in client.get("/").text
    assert client.get("/admin/usage", auth=("admin", "private-password")).status_code == 503


def test_health_metrics_and_local_day_boundary(tmp_path):
    now = [datetime(2026, 10, 21, 23, 59, 59, tzinfo=ZoneInfo("Australia/Sydney")).timestamp()]
    store = UsageStore(str(tmp_path / "usage.sqlite3"), "secret", clock=lambda: now[0])
    store.heartbeat("a" * 32)
    store.record_response(100, False)
    store.record_response(300, True)
    stats = store.snapshot()
    assert (stats["average_ms"], stats["max_ms"], stats["errors"], stats["day"]) == (200, 300, 1, "2026-10-21")
    now[0] += 2
    assert store.snapshot()["day"] == "2026-10-22"
    assert store.snapshot()["requests"] == 0
    store.heartbeat("a" * 32)
    assert store.snapshot()["unique"] == 1
