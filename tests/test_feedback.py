import re

from app import create_app


class EmptyService:
    def matches_for_date(self, *args):
        return []


def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("CARNIVAL_ADMIN_PASSWORD", "test-private-password")
    monkeypatch.setenv("CARNIVAL_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("CARNIVAL_SECRET_KEY", "test-secret")
    return create_app(EmptyService())


def form(client):
    page = client.get("/feedback")
    assert page.status_code == 200
    return re.search(r'name="token" value="([a-f0-9]+)"', page.text).group(1)


def test_report_roundtrip_auth_escaping_and_persistence(monkeypatch, tmp_path):
    app = configured(monkeypatch, tmp_path)
    client = app.test_client()
    assert "Report a problem" in client.get("/").text
    assert "Report a problem" in client.get("/help").text
    token = form(client)
    assert client.post("/feedback", data={"token": "invalid-✓", "message": "A missing score"}).status_code == 400
    result = client.post("/feedback", data={"token": token, "message": "The score is missing <script>alert(1)</script>",
                                         "email": "viewer@example.com", "match_url": "https://play.cricket.com.au/match/example"})
    assert result.status_code == 303
    assert "your report has been saved" in client.get(result.location).text
    assert client.get("/admin/feedback").status_code == 401
    assert client.get("/admin/feedback", auth=("admin", "wrong")).status_code == 401
    # A new app process can read reports from the same database.
    reopened = create_app(EmptyService()).test_client()
    inbox = reopened.get("/admin/feedback", auth=("admin", "test-private-password"))
    assert inbox.status_code == 200
    assert inbox.headers["Cache-Control"] == "no-store"
    assert "viewer@example.com" in inbox.text
    assert "&lt;script&gt;" in inbox.text and "<script>" not in inbox.text
    with app.extensions["usage_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 1


def test_csrf_validation_honeypot_and_limits(monkeypatch, tmp_path):
    app = configured(monkeypatch, tmp_path)
    client = app.test_client()
    assert client.post("/feedback", data={"message": "A missing score"}).status_code == 400
    token = form(client)
    assert client.post("/feedback", data={"token": token, "message": "A missing score"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 400
    for extra in ({"message": "short"}, {"message": "x" * 4001}, {"email": "invalid"}, {"match_url": "javascript:alert(1)"}, {"match_url": "https://[bad"}):
        result = client.post("/feedback", data={"token": token, "message": "The score is missing", **extra})
        assert result.status_code == 400
        assert "The score is missing" in result.text or "short" in result.text or "x" * 4001 in result.text
    assert client.post("/feedback", data={"token": token, "message": "x" * 21000}).status_code == 413
    assert client.post("/feedback", data={"token": token, "message": "A spam message", "website": "spam"}).status_code == 303
    with app.extensions["usage_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    assert client.post("/feedback", data={"token": token, "message": "The score is missing"}).status_code == 303
    token = form(client)
    result = client.post("/feedback", data={"token": token, "message": "A second report too soon"})
    assert result.status_code == 429
    assert "A second report too soon" in result.text


def test_replayed_submission_saved_once(monkeypatch, tmp_path):
    app = configured(monkeypatch, tmp_path)
    client = app.test_client()
    token = form(client)
    cookie = client.get_cookie("session")
    replay = app.test_client()
    replay.set_cookie("session", cookie.value)
    data = {"token": token, "message": "The score is missing again"}
    assert client.post("/feedback", data=data).status_code == 303
    assert replay.post("/feedback", data=data).status_code == 303
    with app.extensions["usage_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 1


def test_unconfigured_feedback_is_not_advertised(monkeypatch):
    monkeypatch.delenv("CARNIVAL_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("CARNIVAL_USAGE_DB", raising=False)
    client = create_app(EmptyService()).test_client()
    assert "Report a problem" not in client.get("/").text
    assert client.get("/feedback").status_code == 503
    assert client.get("/admin/feedback").status_code == 503


def test_failed_save_preserves_message(monkeypatch, tmp_path):
    app = configured(monkeypatch, tmp_path)
    client = app.test_client()
    token = form(client)
    store = app.extensions["usage_store"]
    store.path = str(tmp_path / "nonexistent" / "bad.sqlite3")
    result = client.post("/feedback", data={"token": token, "message": "The score disappeared on my phone"})
    assert result.status_code == 503
    assert "could not be saved" in result.text
    assert "The score disappeared on my phone" in result.text
