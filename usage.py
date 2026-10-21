"""Anonymous daily viewing counts, kept separate from personal feed cookies."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Response, g, render_template, request


class UsageStore:
    def __init__(self, path, secret, timezone="Australia/Sydney", clock=time.time):
        self.path, self.secret, self.timezone, self.clock = path, secret.encode(), ZoneInfo(timezone), clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS viewers (
                    day TEXT NOT NULL, device TEXT NOT NULL, seen REAL NOT NULL,
                    PRIMARY KEY(day, device));
                CREATE INDEX IF NOT EXISTS viewers_seen ON viewers(day, seen);
                CREATE TABLE IF NOT EXISTS daily (
                    day TEXT PRIMARY KEY, peak INTEGER NOT NULL DEFAULT 0,
                    requests INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
                    total_ms REAL NOT NULL DEFAULT 0, max_ms REAL NOT NULL DEFAULT 0,
                    devices INTEGER NOT NULL DEFAULT 0);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=0.5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def day(self):
        return datetime.fromtimestamp(self.clock(), self.timezone).date().isoformat()

    def heartbeat(self, token):
        now, day = self.clock(), self.day()
        device = hmac.new(self.secret, f"{day}:{token}".encode(), hashlib.sha256).hexdigest()
        with self.connect() as db:
            # Serialize peak calculation across web workers as well as threads.
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO viewers VALUES (?,?,?) ON CONFLICT(day,device) DO UPDATE SET seen=excluded.seen", (day, device, now))
            active = db.execute("SELECT COUNT(*) FROM viewers WHERE day=? AND seen>?", (day, now - 120)).fetchone()[0]
            unique = db.execute("SELECT COUNT(*) FROM viewers WHERE day=?", (day,)).fetchone()[0]
            db.execute("INSERT INTO daily(day,peak,devices) VALUES (?,?,?) ON CONFLICT(day) DO UPDATE SET peak=MAX(peak,excluded.peak), devices=excluded.devices", (day, active, unique))
            # Keep daily browser hashes briefly; retain aggregates for 90 days.
            db.execute("DELETE FROM viewers WHERE day < ?", ((datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat(),))
            db.execute("DELETE FROM daily WHERE day < ?", ((datetime.fromisoformat(day) - timedelta(days=90)).date().isoformat(),))

    def record_response(self, milliseconds, failed):
        with self.connect() as db:
            db.execute("""INSERT INTO daily(day,requests,errors,total_ms,max_ms) VALUES (?,1,?,?,?)
                ON CONFLICT(day) DO UPDATE SET requests=requests+1, errors=errors+excluded.errors,
                total_ms=total_ms+excluded.total_ms, max_ms=MAX(max_ms,excluded.max_ms)""",
                (self.day(), int(failed), milliseconds, milliseconds))

    def snapshot(self):
        day, now = self.day(), self.clock()
        with self.connect() as db:
            active = db.execute("SELECT COUNT(*) FROM viewers WHERE day=? AND seen>?", (day, now - 120)).fetchone()[0]
            unique = db.execute("SELECT COUNT(*) FROM viewers WHERE day=?", (day,)).fetchone()[0]
            row = db.execute("SELECT peak,requests,errors,total_ms,max_ms FROM daily WHERE day=?", (day,)).fetchone() or (0, 0, 0, 0, 0)
            history = db.execute("SELECT day,peak,devices,requests,errors FROM daily ORDER BY day DESC LIMIT 14").fetchall()
        peak, count, errors, total, maximum = row
        return dict(day=day, timezone=str(self.timezone), active=active, unique=unique, peak=peak,
                    requests=count, errors=errors, average_ms=round(total / count) if count else 0,
                    max_ms=round(maximum), history=history)


def admin_auth(password):
    if not password:
        return Response("Administrator access is not configured.", 503)
    auth = request.authorization
    if not auth or auth.username != "admin" or not secrets.compare_digest(
            (auth.password or "").encode(), password.encode()):
        return Response("Administrator login required.", 401,
                        {"WWW-Authenticate": 'Basic realm="Carnival Live admin", charset="UTF-8"'})
    return None


def register_usage(app):
    password = os.getenv("CARNIVAL_ADMIN_PASSWORD", "")
    path = os.getenv("CARNIVAL_USAGE_DB", "")
    store = None
    if password and path:
        try:
            store = UsageStore(path, app.secret_key, os.getenv("CARNIVAL_USAGE_TIMEZONE", "Australia/Sydney"))
        except Exception:
            app.logger.exception("Usage monitoring could not start; scores remain available")
    app.extensions["usage_store"] = store

    @app.context_processor
    def usage_context():
        return {"usage_enabled": store is not None}

    @app.before_request
    def start_usage_timer():
        g.usage_started = time.monotonic()

    @app.after_request
    def finish_usage_timer(response):
        if request.path.startswith("/admin/") or request.path in {"/usage/heartbeat", "/feedback"}:
            response.headers["Cache-Control"] = "no-store"
        if store and (request.path == "/" or request.path.startswith("/setup")):
            try:
                store.record_response((time.monotonic() - g.usage_started) * 1000,
                                      response.status_code >= 500 or bool(getattr(g, "usage_source_error", False)))
            except Exception:
                app.logger.exception("Could not record usage response")
        return response

    @app.post("/usage/heartbeat")
    def usage_heartbeat():
        if store is None:
            return "", 503
        # Only our own scores page should submit browser activity.
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return "", 403
        if request.content_length is None or request.content_length > 256:
            return "", 400
        body = request.get_json(silent=True)
        token = body.get("device") if isinstance(body, dict) else None
        if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            return "", 400
        try:
            store.heartbeat(token)
        except Exception:
            app.logger.exception("Could not record viewer heartbeat")
            return "", 503
        return "", 204

    @app.get("/admin/usage")
    def usage_admin():
        denied = admin_auth(password)
        if denied is not None:
            return denied
        if store is None:
            return "Usage storage is unavailable. Check CARNIVAL_USAGE_DB and the service logs.", 503
        try:
            stats = store.snapshot()
        except Exception:
            app.logger.exception("Could not read usage statistics")
            return "Usage statistics are temporarily unavailable.", 503
        return render_template("usage.html", stats=stats)
