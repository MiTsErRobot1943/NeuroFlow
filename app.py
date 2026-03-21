import os
import secrets

from flask import Flask, flash, redirect, render_template, request, session, url_for

from db_setup import initialize_database, verify_user

app = Flask(
    __name__,
    template_folder="Template",
    static_folder="Template",
    static_url_path="/static",
)

app.config.update(
    SECRET_KEY=os.getenv("NEUROFLOW_SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# Ensure DB schema exists at startup.
initialize_database()


def _ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _validate_csrf() -> bool:
    token = session.get("csrf_token")
    posted = request.form.get("csrf_token", "")
    return bool(token and posted and secrets.compare_digest(token, posted))


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; "
        "img-src 'self' data:;"
    )
    return response

@app.route("/")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template(
        "Dashboard.html",
        username=session.get("username", "User"),
        csrf_token=_ensure_csrf_token(),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not _validate_csrf():
            flash("Invalid request token. Please try again.", "error")
            return redirect(url_for("login"))

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = verify_user(username=username, password=password)

        if user:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("Login.html", csrf_token=_ensure_csrf_token())


@app.route("/logout", methods=["POST"])
def logout():
    if not _validate_csrf():
        flash("Invalid request token.", "error")
        return redirect(url_for("dashboard"))

    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run()
