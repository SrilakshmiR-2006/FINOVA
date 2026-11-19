"""FINOVA - finance analytics & budget tracking (Flask + SQLite)."""
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import finance as fin

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FINOVA_DB", os.path.join(BASE_DIR, "finova.db"))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FINOVA_SECRET") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)
# Keep sessions valid across restarts in dev by persisting a generated secret.
_secret_file = os.path.join(BASE_DIR, ".secret_key")
if not os.environ.get("FINOVA_SECRET"):
    if os.path.exists(_secret_file):
        app.config["SECRET_KEY"] = open(_secret_file).read().strip()
    else:
        with open(_secret_file, "w") as f:
            f.write(app.config["SECRET_KEY"])

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL DEFAULT '',
  dob TEXT,
  phone TEXT,
  monthly_income REAL NOT NULL DEFAULT 0,
  daily_income REAL NOT NULL DEFAULT 0,
  savings_goal_pct REAL NOT NULL DEFAULT 20,
  is_admin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('income','expense','saving')),
  amount REAL NOT NULL CHECK (amount > 0),
  category TEXT NOT NULL,
  note TEXT,
  occurred_on TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS transactions_user_date_idx ON transactions (user_id, occurred_on DESC);
CREATE TABLE IF NOT EXISTS reset_tokens (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);
"""

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PHONE_RE = re.compile(r"^[+\d\s()-]*$")


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.commit()
    db.close()


init_db()


# ---------------------------------------------------------------- auth helpers
def current_user():
    if "user" in g:
        return g.user
    uid = session.get("uid")
    g.user = None
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify(error="Not signed in"), 401
            return redirect(url_for("auth"))
        return view(*a, **kw)
    return wrapped


@app.context_processor
def inject_globals():
    return {"me": current_user(), "categories": fin.CATEGORIES,
            "password_rules": [{"id": i, "label": l} for i, l, _ in fin.PASSWORD_RULES]}


@app.before_request
def csrf_guard():
    # API writes must be same-origin JSON; form posts carry a session token.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.path.startswith("/api/"):
            if request.headers.get("X-Requested-With") != "finova":
                abort(403)
        else:
            tok = session.get("csrf")
            if not tok or request.form.get("csrf") != tok:
                abort(400, "Invalid form token. Reload the page and try again.")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


# ---------------------------------------------------------------- pages
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/auth", methods=["GET", "POST"])
def auth():
    if request.method == "GET":
        if current_user():
            return redirect(url_for("dashboard"))
        return render_template("auth.html")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    mode = request.form.get("mode", "user")
    if not EMAIL_RE.match(email):
        flash("Enter a valid email", "error")
        return render_template("auth.html", mode=mode, email=email), 400
    if not password:
        flash("Enter your password", "error")
        return render_template("auth.html", mode=mode, email=email), 400
    user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Email or password is incorrect.", "error")
        return render_template("auth.html", mode=mode, email=email), 401
    if mode == "admin" and not user["is_admin"]:
        flash("This account doesn't have admin access.", "error")
        return render_template("auth.html", mode=mode, email=email), 403
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    return redirect(url_for("admin" if mode == "admin" else "dashboard"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")
    name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    pw = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    err = None
    if not 2 <= len(name) <= 100:
        err = "Enter your full name"
    elif not EMAIL_RE.match(email) or len(email) > 255:
        err = "Enter a valid email"
    elif not fin.password_is_strong(pw) or pw != confirm:
        err = "Please meet all password requirements."
    if err:
        flash(err, "error")
        return render_template("signup.html", full_name=name, email=email), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        flash("An account with this email already exists.", "error")
        return render_template("signup.html", full_name=name, email=email), 409
    # The first account created becomes admin.
    is_admin = 0 if db.execute("SELECT 1 FROM users WHERE is_admin = 1").fetchone() else 1
    db.execute("INSERT INTO users (email, password_hash, full_name, is_admin) VALUES (?,?,?,?)",
               (email, generate_password_hash(pw), name, is_admin))
    db.commit()
    return render_template("signup_done.html", sent_to=email)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot.html")
    email = request.form.get("email", "").strip().lower()
    if not EMAIL_RE.match(email):
        flash("Enter a valid email", "error")
        return render_template("forgot.html"), 400
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    dev_link = None
    if user:
        token = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        db.execute("INSERT INTO reset_tokens (token, user_id, expires_at) VALUES (?,?,?)",
                   (token, user["id"], expires))
        db.commit()
        link = url_for("reset_password", token=token, _external=True)
        print(f"[FINOVA] Password reset link for {email}: {link}")
        # No mail server is configured locally, so show the link in dev mode.
        if app.debug or os.environ.get("FINOVA_SHOW_RESET_LINK") == "1":
            dev_link = link
    return render_template("forgot.html", sent=True, email=email, dev_link=dev_link)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token = request.values.get("token", "")
    db = get_db()
    row = db.execute("SELECT * FROM reset_tokens WHERE token = ?", (token,)).fetchone()
    valid = bool(row) and datetime.fromisoformat(row["expires_at"]) > datetime.utcnow()
    if request.method == "GET":
        return render_template("reset.html", ready=valid, token=token)
    pw = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    if not valid:
        flash("This reset link is invalid or has expired.", "error")
        return render_template("reset.html", ready=False, token=token), 400
    if not fin.password_is_strong(pw) or pw != confirm:
        flash("Please meet all password requirements.", "error")
        return render_template("reset.html", ready=True, token=token), 400
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (generate_password_hash(pw), row["user_id"]))
    db.execute("DELETE FROM reset_tokens WHERE user_id = ?", (row["user_id"],))
    db.commit()
    session.clear()
    session["uid"] = row["user_id"]
    session["flash_ok"] = "Password updated"
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth"))


def profile_dict(u):
    return {
        "id": u["id"], "full_name": u["full_name"], "email": u["email"], "dob": u["dob"],
        "phone": u["phone"], "monthly_income": u["monthly_income"],
        "daily_income": u["daily_income"], "savings_goal_pct": u["savings_goal_pct"],
    }


@app.route("/dashboard")
@login_required
def dashboard():
    ok = session.pop("flash_ok", None)
    if ok:
        flash(ok, "success")
    return render_template("dashboard.html", profile=profile_dict(current_user()))


@app.route("/profile")
@login_required
def profile():
    u = current_user()
    return render_template("profile.html", p=profile_dict(u))


@app.route("/admin")
@login_required
def admin():
    u = current_user()
    if not u["is_admin"]:
        return render_template("admin.html", allowed=False)
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at, id").fetchall()
    txns = db.execute("SELECT user_id, type, amount, occurred_on FROM transactions").fetchall()
    now = date.today()
    rows = []
    for p in users:
        mine = [dict(t) for t in txns if t["user_id"] == p["id"]]
        month = [t for t in mine if fin.is_same_month(t["occurred_on"], now)]
        mt = fin.totals(month)
        rows.append({
            "name": p["full_name"], "email": p["email"], "all": fin.totals(mine),
            "score": fin.finance_score(mt, p["savings_goal_pct"]), "has_income": mt["income"] > 0,
        })
    s = {k: sum(r["all"][k] for r in rows) for k in ("income", "expense", "saving")}
    return render_template("admin.html", allowed=True, rows=rows, sums=s)


# ---------------------------------------------------------------- API
def txn_dict(r):
    return {"id": r["id"], "type": r["type"], "amount": r["amount"], "category": r["category"],
            "note": r["note"], "occurred_on": r["occurred_on"]}


@app.get("/api/transactions")
@login_required
def api_list():
    rows = get_db().execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY occurred_on DESC, id DESC LIMIT 1000",
        (current_user()["id"],)).fetchall()
    return jsonify([txn_dict(r) for r in rows])


@app.post("/api/transactions")
@login_required
def api_add():
    d = request.get_json(silent=True) or {}
    t = d.get("type")
    try:
        amount = float(d.get("amount"))
    except (TypeError, ValueError):
        return jsonify(error="Enter an amount"), 400
    category = str(d.get("category", "")).strip()
    occurred = str(d.get("occurred_on", ""))
    note = (d.get("note") or "").strip()[:200] or None
    if t not in fin.TXN_TYPES:
        return jsonify(error="Invalid type"), 400
    if not amount > 0:
        return jsonify(error="Amount must be above 0"), 400
    if amount > 1_000_000_000:
        return jsonify(error="Amount is too large"), 400
    if not category:
        return jsonify(error="Pick a category"), 400
    if not DATE_RE.match(occurred):
        return jsonify(error="Pick a date"), 400
    try:
        date.fromisoformat(occurred)
    except ValueError:
        return jsonify(error="Pick a date"), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO transactions (user_id, type, amount, category, note, occurred_on) "
        "VALUES (?,?,?,?,?,?)",
        (current_user()["id"], t, round(amount, 2), category, note, occurred))
    db.commit()
    row = db.execute("SELECT * FROM transactions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(txn_dict(row)), 201


@app.delete("/api/transactions/<int:tid>")
@login_required
def api_delete(tid):
    db = get_db()
    db.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tid, current_user()["id"]))
    db.commit()
    return jsonify(ok=True)


@app.post("/api/profile")
@login_required
def api_profile():
    d = request.get_json(silent=True) or {}
    name = str(d.get("full_name", "")).strip()
    dob = d.get("dob") or None
    phone = (d.get("phone") or "").strip() or None
    try:
        monthly = float(d.get("monthly_income") or 0)
        daily = float(d.get("daily_income") or 0)
        goal = float(d.get("savings_goal_pct") or 0)
    except (TypeError, ValueError):
        return jsonify(error="Income and goal must be numbers"), 400
    if not 2 <= len(name) <= 100:
        return jsonify(error="Enter your name"), 400
    if dob:
        if not DATE_RE.match(dob):
            return jsonify(error="Invalid date of birth"), 400
        try:
            if date.fromisoformat(dob) >= date.today():
                return jsonify(error="Date of birth must be in the past"), 400
        except ValueError:
            return jsonify(error="Invalid date of birth"), 400
    if phone and (len(phone) > 20 or not PHONE_RE.match(phone)):
        return jsonify(error="Phone can only contain digits, spaces, +, - and ()"), 400
    if not (0 <= monthly <= 1_000_000_000 and 0 <= daily <= 100_000_000):
        return jsonify(error="Income is out of range"), 400
    if not 0 <= goal <= 100:
        return jsonify(error="Savings goal must be 0-100"), 400
    db = get_db()
    db.execute("UPDATE users SET full_name=?, dob=?, phone=?, monthly_income=?, daily_income=?, "
               "savings_goal_pct=? WHERE id=?",
               (name, dob, phone, monthly, daily, goal, current_user()["id"]))
    db.commit()
    return jsonify(ok=True)


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FINOVA_DEBUG", "1") == "1")
