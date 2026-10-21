"""Small private report inbox using the configured persistent monitoring database."""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime
from urllib.parse import urlsplit

from flask import redirect, render_template, request, session, url_for

from usage import admin_auth


def register_feedback(app):
    store = app.extensions.get("usage_store")
    if store:
        try:
            with store.connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS feedback (
                    token TEXT PRIMARY KEY, sender TEXT NOT NULL, created REAL NOT NULL,
                    message TEXT NOT NULL, email TEXT NOT NULL, match_url TEXT NOT NULL)""")
                db.execute("CREATE INDEX IF NOT EXISTS feedback_created ON feedback(created)")
        except Exception:
            app.logger.exception("Feedback storage unavailable")
            store = None

    @app.context_processor
    def feedback_context():
        return {"feedback_enabled": store is not None}

    @app.route("/feedback", methods=["GET", "POST"])
    def feedback():
        values = {"message": "", "email": "", "match_url": ""}
        error, status = "", 200
        if store is None:
            return render_template("feedback.html", unavailable=True, values=values), 503
        if request.method == "GET" and request.args.get("sent") == "1":
            return render_template("feedback.html", sent=True, values=values)
        if request.method == "POST":
            if request.content_length is None or request.content_length > 20000:
                return "Report is too large. Please shorten it and try again.", 413
            token = session.get("feedback_token", "")
            if (request.headers.get("Sec-Fetch-Site") == "cross-site" or not token
                    or not secrets.compare_digest(token.encode(), request.form.get("token", "").encode())):
                return "Please reopen Report a problem and try again.", 400
            if request.form.get("website"):
                return redirect(url_for("feedback", sent="1"), code=303)
            values = {key: request.form.get(key, "").strip() for key in values}
            if not 10 <= len(values["message"]) <= 4000:
                error = "Please describe the problem in 10 to 4,000 characters."
            elif values["email"] and (len(values["email"]) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"])):
                error = "Enter a valid email address, or leave it blank."
            elif values["match_url"]:
                try:
                    link = urlsplit(values["match_url"])
                    if len(values["match_url"]) > 1000 or link.scheme not in {"https", "http"} or not link.hostname or link.username or link.password:
                        error = "Enter a full match link starting with https://, or leave it blank."
                except ValueError:
                    error = "Enter a valid match link, or leave it blank."
            if error:
                status = 400
            else:
                now = store.clock()
                sender = hmac.new(app.secret_key.encode(), session["feedback_sender"].encode(), hashlib.sha256).hexdigest()
                try:
                    with store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        db.execute("DELETE FROM feedback WHERE created < ?", (now - 90 * 86400,))
                        duplicate = db.execute("SELECT 1 FROM feedback WHERE token=?", (token,)).fetchone()
                        recent = db.execute("SELECT 1 FROM feedback WHERE sender=? AND created>?", (sender, now - 60)).fetchone()
                        count = db.execute("SELECT COUNT(*) FROM feedback WHERE created>?", (now - 86400,)).fetchone()[0]
                        if duplicate:
                            return redirect(url_for("feedback", sent="1"), code=303)
                        if count >= 500:
                            error, status = "Reports are temporarily busy. Your message has not been sent; please try again later.", 429
                        elif recent:
                            error, status = "Please wait a minute before sending another report. Your message has not been sent.", 429
                        else:
                            db.execute("INSERT INTO feedback VALUES (?,?,?,?,?,?)",
                                       (token, sender, now, values["message"], values["email"], values["match_url"]))
                    if not error:
                        session.pop("feedback_token", None)
                        return redirect(url_for("feedback", sent="1"), code=303)
                except Exception:
                    app.logger.exception("Could not save problem report")
                    error, status = "Your report could not be saved. Please try again shortly; your message is still below.", 503
        if "feedback_token" not in session:
            session["feedback_token"] = secrets.token_hex(24)
        if "feedback_sender" not in session:
            session["feedback_sender"] = secrets.token_hex(24)
        return render_template("feedback.html", values=values, error=error, token=session["feedback_token"]), status

    @app.get("/admin/feedback")
    def feedback_admin():
        denied = admin_auth(os.getenv("CARNIVAL_ADMIN_PASSWORD", ""))
        if denied is not None:
            return denied
        if store is None:
            return "Feedback storage is unavailable. Configure the usage database first.", 503
        try:
            with store.connect() as db:
                db.execute("DELETE FROM feedback WHERE created < ?", (store.clock() - 90 * 86400,))
                rows = db.execute("SELECT created,message,email,match_url FROM feedback ORDER BY created DESC LIMIT 100").fetchall()
            reports = [dict(created=datetime.fromtimestamp(row[0], store.timezone).strftime("%d %b %Y %I:%M %p"),
                            message=row[1], email=row[2], match_url=row[3]) for row in rows]
        except Exception:
            app.logger.exception("Could not read problem reports")
            return "Reports are temporarily unavailable. Please try again shortly.", 503
        return render_template("feedback_admin.html", reports=reports, timezone=str(store.timezone))
