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
CREATE TABLE IF NOT EXISTS investments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  quantity REAL NOT NULL CHECK (quantity > 0),
  buy_price REAL NOT NULL CHECK (buy_price >= 0),
  current_price REAL NOT NULL CHECK (current_price >= 0),
  purchased_on TEXT,
  price_updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS investments_user_idx ON investments (user_id);
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  target_amount REAL NOT NULL CHECK (target_amount > 0),
  target_date TEXT NOT NULL,
  completed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS goals_user_idx ON goals (user_id);
CREATE TABLE IF NOT EXISTS goal_contributions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount REAL NOT NULL CHECK (amount > 0),
  contributed_on TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
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
    # Add new user columns to databases created by older versions (keeps existing data).
    cols = {r[1] for r in db.execute("PRAGMA table_info(users)")}
    for col, ddl in (("monthly_budget", "REAL NOT NULL DEFAULT 0"),
                     ("yearly_budget", "REAL NOT NULL DEFAULT 0"),
                     ("currency", "TEXT NOT NULL DEFAULT 'USD'")):
        if col not in cols:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    db.commit()
    db.close()


init_db()


# ---------------------------------------------------------------- currency rates
_rates_cache = {"at": 0.0, "rates": dict(fin.FALLBACK_RATES), "live": False}


def get_rates():
    """Live USD-based rates (cached 6h); falls back to built-in rates when offline."""
    import json, time, urllib.request
    if time.time() - _rates_cache["at"] < 6 * 3600:
        return _rates_cache
    _rates_cache["at"] = time.time()
    if os.environ.get("FINOVA_OFFLINE") == "1":
        return _rates_cache
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=4) as r:
            data = json.load(r)
        live = {k: float(data["rates"][k]) for k in fin.CURRENCIES if k in data.get("rates", {})}
        if len(live) == len(fin.CURRENCIES):
            _rates_cache.update(rates=live, live=True)
    except Exception as exc:  # network down: keep fallback/previous rates
        print(f"[FINOVA] Using fallback currency rates ({exc})")
    return _rates_cache


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
    u = current_user()
    return {"me": u, "categories": fin.CATEGORIES, "currencies": fin.CURRENCIES,
            "currency": (u["currency"] if u else "USD"), "rates": get_rates(),
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


@app.route("/wealth")
@login_required
def wealth():
    return render_template("wealth.html", asset_types=fin.ASSET_TYPES)


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
        (current_user()["id"], t, round(amount, 6), category, note, occurred))
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


# ---------------------------------------------------------------- API: shared validation
class Bad(Exception):
    pass


@app.errorhandler(Bad)
def _bad(e):
    return jsonify(error=str(e)), 400


def num(d, key, label, lo=0.0, hi=1e12, allow_zero=False):
    try:
        v = float(d.get(key))
    except (TypeError, ValueError):
        raise Bad(f"Enter {label}")
    if v != v or v < lo or v > hi or (not allow_zero and v == 0):
        raise Bad(f"{label.capitalize()} is out of range")
    return v


def text(d, key, label, maxlen=100):
    v = str(d.get(key) or "").strip()
    if not v:
        raise Bad(f"Enter {label}")
    return v[:maxlen]


def iso_date(d, key, label, required=True):
    v = str(d.get(key) or "")
    if not v and not required:
        return None
    try:
        if not DATE_RE.match(v):
            raise ValueError
        date.fromisoformat(v)
    except ValueError:
        raise Bad(f"Pick {label}")
    return v


def uid():
    return current_user()["id"]


# ---------------------------------------------------------------- API: investments
def inv_dict(r):
    d = {k: r[k] for k in ("id", "name", "asset_type", "quantity", "buy_price", "current_price",
                           "purchased_on", "price_updated_at")}
    d.update(fin.investment_metrics(r))
    return d


@app.get("/api/investments")
@login_required
def api_investments():
    rows = get_db().execute("SELECT * FROM investments WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                            (uid(),)).fetchall()
    return jsonify(items=[inv_dict(r) for r in rows], summary=fin.portfolio_summary(rows))


def inv_fields(d):
    asset = str(d.get("asset_type") or "")
    if asset not in fin.ASSET_TYPES:
        raise Bad("Pick an asset type")
    return (text(d, "name", "a name"), asset, num(d, "quantity", "a quantity"),
            num(d, "buy_price", "a buy price", allow_zero=True),
            num(d, "current_price", "a current price", allow_zero=True),
            iso_date(d, "purchased_on", "a purchase date", required=False))


@app.post("/api/investments")
@login_required
def api_inv_add():
    f = inv_fields(request.get_json(silent=True) or {})
    db = get_db()
    cur = db.execute("INSERT INTO investments (user_id, name, asset_type, quantity, buy_price, current_price, "
                     "purchased_on) VALUES (?,?,?,?,?,?,?)", (uid(), *f))
    db.commit()
    return jsonify(inv_dict(db.execute("SELECT * FROM investments WHERE id = ?", (cur.lastrowid,)).fetchone())), 201


@app.put("/api/investments/<int:iid>")
@login_required
def api_inv_edit(iid):
    f = inv_fields(request.get_json(silent=True) or {})
    db = get_db()
    cur = db.execute("UPDATE investments SET name=?, asset_type=?, quantity=?, buy_price=?, current_price=?, "
                     "purchased_on=?, price_updated_at=datetime('now') WHERE id=? AND user_id=?", (*f, iid, uid()))
    db.commit()
    if not cur.rowcount:
        return jsonify(error="Investment not found"), 404
    return jsonify(ok=True)


@app.patch("/api/investments/<int:iid>/price")
@login_required
def api_inv_price(iid):
    price = num(request.get_json(silent=True) or {}, "current_price", "a current price", allow_zero=True)
    db = get_db()
    cur = db.execute("UPDATE investments SET current_price=?, price_updated_at=datetime('now') "
                     "WHERE id=? AND user_id=?", (price, iid, uid()))
    db.commit()
    if not cur.rowcount:
        return jsonify(error="Investment not found"), 404
    return jsonify(ok=True)


@app.delete("/api/investments/<int:iid>")
@login_required
def api_inv_delete(iid):
    db = get_db()
    db.execute("DELETE FROM investments WHERE id = ? AND user_id = ?", (iid, uid()))
    db.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- API: goals
def goals_payload():
    db = get_db()
    goals = db.execute("SELECT * FROM goals WHERE user_id = ? ORDER BY target_date, id", (uid(),)).fetchall()
    contribs = db.execute("SELECT * FROM goal_contributions WHERE user_id = ? "
                          "ORDER BY contributed_on DESC, id DESC", (uid(),)).fetchall()
    out = []
    for g_ in goals:
        mine = [dict(id=c["id"], amount=c["amount"], contributed_on=c["contributed_on"], note=c["note"])
                for c in contribs if c["goal_id"] == g_["id"]]
        prog = fin.goal_progress(g_["target_amount"], sum(c["amount"] for c in mine))
        days_left = (date.fromisoformat(g_["target_date"]) - date.today()).days
        out.append({"id": g_["id"], "name": g_["name"], "target_amount": g_["target_amount"],
                    "target_date": g_["target_date"], "completed_at": g_["completed_at"],
                    "days_left": days_left, "contributions": mine, **prog})
    t_target = sum(x["target_amount"] for x in out)
    t_saved = sum(min(x["saved"], x["target_amount"]) for x in out)
    return {"items": out, "summary": {"count": len(out), "completed": sum(x["completed"] for x in out),
                                      "target": round(t_target, 2), "saved": round(t_saved, 2),
                                      "pct": round(min(100.0, fin.pct(t_saved, t_target)), 2)}}


def sync_goal_completion(db, gid):
    """Stamp/clear completed_at; returns True when this change just completed the goal."""
    g_ = db.execute("SELECT * FROM goals WHERE id = ?", (gid,)).fetchone()
    saved = db.execute("SELECT COALESCE(SUM(amount),0) FROM goal_contributions WHERE goal_id = ?", (gid,)).fetchone()[0]
    done = fin.goal_progress(g_["target_amount"], saved)["completed"]
    if done and not g_["completed_at"]:
        db.execute("UPDATE goals SET completed_at = datetime('now') WHERE id = ?", (gid,))
        return True
    if not done and g_["completed_at"]:
        db.execute("UPDATE goals SET completed_at = NULL WHERE id = ?", (gid,))
    return False


def own_goal(gid):
    g_ = get_db().execute("SELECT * FROM goals WHERE id = ? AND user_id = ?", (gid, uid())).fetchone()
    if not g_:
        abort(404)
    return g_


@app.get("/api/goals")
@login_required
def api_goals():
    return jsonify(goals_payload())


def goal_fields(d):
    return (text(d, "name", "a goal name"), num(d, "target_amount", "a target amount"),
            iso_date(d, "target_date", "a target date"))


@app.post("/api/goals")
@login_required
def api_goal_add():
    f = goal_fields(request.get_json(silent=True) or {})
    db = get_db()
    db.execute("INSERT INTO goals (user_id, name, target_amount, target_date) VALUES (?,?,?,?)", (uid(), *f))
    db.commit()
    return jsonify(ok=True), 201


@app.put("/api/goals/<int:gid>")
@login_required
def api_goal_edit(gid):
    own_goal(gid)
    f = goal_fields(request.get_json(silent=True) or {})
    db = get_db()
    db.execute("UPDATE goals SET name=?, target_amount=?, target_date=? WHERE id=?", (*f, gid))
    just_done = sync_goal_completion(db, gid)
    db.commit()
    return jsonify(ok=True, completed=just_done)


@app.delete("/api/goals/<int:gid>")
@login_required
def api_goal_delete(gid):
    own_goal(gid)
    db = get_db()
    db.execute("DELETE FROM goals WHERE id = ?", (gid,))
    db.commit()
    return jsonify(ok=True)


@app.post("/api/goals/<int:gid>/contributions")
@login_required
def api_goal_contribute(gid):
    own_goal(gid)
    d = request.get_json(silent=True) or {}
    amount = num(d, "amount", "an amount", hi=1e10)
    on = iso_date(d, "contributed_on", "a date")
    note = (str(d.get("note") or "").strip()[:200]) or None
    db = get_db()
    db.execute("INSERT INTO goal_contributions (goal_id, user_id, amount, contributed_on, note) VALUES (?,?,?,?,?)",
               (gid, uid(), round(amount, 6), on, note))
    just_done = sync_goal_completion(db, gid)
    db.commit()
    return jsonify(ok=True, completed=just_done), 201


@app.delete("/api/contributions/<int:cid>")
@login_required
def api_contrib_delete(cid):
    db = get_db()
    row = db.execute("SELECT goal_id FROM goal_contributions WHERE id = ? AND user_id = ?", (cid, uid())).fetchone()
    if row:
        db.execute("DELETE FROM goal_contributions WHERE id = ?", (cid,))
        sync_goal_completion(db, row["goal_id"])
        db.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- API: budget, currency, summary
def budget_payload():
    u = current_user()
    today = date.today()
    db = get_db()
    m = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type='expense' "
                   "AND substr(occurred_on,1,7)=?", (u["id"], today.strftime("%Y-%m"))).fetchone()[0]
    y = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type='expense' "
                   "AND substr(occurred_on,1,4)=?", (u["id"], str(today.year))).fetchone()[0]
    total = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type='expense'",
                       (u["id"],)).fetchone()[0]
    return {"monthly": fin.budget_status(m, u["monthly_budget"]),
            "yearly": fin.budget_status(y, u["yearly_budget"]), "total_expenses": round(total, 2)}


@app.get("/api/budget")
@login_required
def api_budget():
    return jsonify(budget_payload())


@app.post("/api/budget")
@login_required
def api_budget_set():
    d = request.get_json(silent=True) or {}
    monthly = num(d, "monthly_budget", "a monthly budget", allow_zero=True)
    yearly = num(d, "yearly_budget", "a yearly budget", allow_zero=True)
    db = get_db()
    db.execute("UPDATE users SET monthly_budget=?, yearly_budget=? WHERE id=?", (monthly, yearly, uid()))
    db.commit()
    g.pop("user", None)
    return jsonify(budget_payload())


@app.post("/api/currency")
@login_required
def api_currency():
    code = str((request.get_json(silent=True) or {}).get("currency", ""))
    if code not in fin.CURRENCIES:
        return jsonify(error="Unsupported currency"), 400
    db = get_db()
    db.execute("UPDATE users SET currency=? WHERE id=?", (code, uid()))
    db.commit()
    return jsonify(ok=True)


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found"), 404
    return render_template("404.html"), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FINOVA_DEBUG", "1") == "1")
