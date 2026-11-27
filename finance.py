"""Money math and validation rules for FINOVA (pure functions, fully testable)."""
import math
import re
from datetime import date

TXN_TYPES = ("income", "expense", "saving")

CATEGORIES = {
    "income": ["Salary", "Freelance", "Business", "Investments", "Gifts", "Other"],
    "expense": ["Food & Dining", "Transport", "Shopping", "Bills & Utilities", "Rent",
                "Health", "Entertainment", "Education", "Travel", "Other"],
    "saving": ["Emergency Fund", "Investments", "Retirement", "Travel", "Education", "Other"],
}

PASSWORD_RULES = [
    ("len", "At least 8 characters", lambda p: len(p) >= 8),
    ("upper", "One uppercase letter", lambda p: re.search(r"[A-Z]", p) is not None),
    ("lower", "One lowercase letter", lambda p: re.search(r"[a-z]", p) is not None),
    ("num", "One number", lambda p: re.search(r"\d", p) is not None),
    ("special", "One special character", lambda p: re.search(r"[^A-Za-z0-9]", p) is not None),
]


def password_is_strong(p: str) -> bool:
    return all(test(p) for _, _, test in PASSWORD_RULES)


def totals(txns):
    t = {"income": 0.0, "expense": 0.0, "saving": 0.0}
    for x in txns:
        t[x["type"]] += float(x["amount"])
    return t


def available_balance(t):
    """Everything earned minus what was spent and set aside as savings."""
    return t["income"] - t["expense"] - t["saving"]


def finance_score(t, goal_pct):
    """0-100 score: 60 pts kept-vs-goal, 25 pts share not spent, 15 pts savings habit."""
    if t["income"] <= 0:
        return 0
    goal = max(goal_pct, 1) / 100
    clamp = lambda n: min(1.0, max(0.0, n))
    kept = (t["income"] - t["expense"]) / t["income"]
    goal_part = clamp(kept / goal) * 60
    spend_part = clamp(1 - t["expense"] / t["income"]) * 25
    habit_part = clamp(t["saving"] / (t["income"] * goal)) * 15
    return int(math.floor(goal_part + spend_part + habit_part + 0.5))


def score_label(score):
    if score >= 80:
        return "Excellent"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Fair"
    return "Needs care"


def age_from_dob(dob, today=None):
    if not dob:
        return None
    today = today or date.today()
    try:
        y, m, d = (int(x) for x in dob.split("-"))
    except ValueError:
        return None
    age = today.year - y
    if today.month < m or (today.month == m and today.day < d):
        age -= 1
    return age if age >= 0 else None


def is_same_month(iso, ref):
    y, m, _ = (int(x) for x in iso.split("-"))
    return y == ref.year and m == ref.month


# ---------------------------------------------------------------- investments
ASSET_TYPES = ["Stocks", "Mutual Funds", "Gold", "Fixed Deposits", "Bonds", "Crypto",
               "Real Estate", "Other"]


def pct(part, whole):
    return (part / whole * 100) if whole else 0.0


def investment_metrics(inv):
    """Per holding: invested = units x buy price, value = units x current price."""
    invested = float(inv["quantity"]) * float(inv["buy_price"])
    value = float(inv["quantity"]) * float(inv["current_price"])
    pl = value - invested
    return {"invested": round(invested, 2), "value": round(value, 2),
            "pl": round(pl, 2), "return_pct": round(pct(pl, invested), 2)}


def portfolio_summary(items):
    """Overall return is weighted: total P/L / total invested (not an average of %s)."""
    invested = value = 0.0
    alloc = {}
    for inv in items:
        m = investment_metrics(inv)
        invested += m["invested"]
        value += m["value"]
        alloc[inv["asset_type"]] = alloc.get(inv["asset_type"], 0.0) + m["value"]
    pl = value - invested
    allocation = [{"asset_type": k, "value": round(v, 2), "pct": round(pct(v, value), 2)}
                  for k, v in sorted(alloc.items(), key=lambda kv: -kv[1])]
    return {"invested": round(invested, 2), "value": round(value, 2), "pl": round(pl, 2),
            "return_pct": round(pct(pl, invested), 2), "count": len(items),
            "allocation": allocation}


# ---------------------------------------------------------------- goals
def goal_progress(target, saved):
    target, saved = float(target), float(saved)
    return {"saved": round(saved, 2), "remaining": round(max(0.0, target - saved), 2),
            "pct": round(min(100.0, pct(saved, target)), 2), "completed": target > 0 and saved >= target}


# ---------------------------------------------------------------- budgets
def budget_status(spent, budget):
    """Alert levels: none (no budget), ok (<80%), warn (80-100%), over (>100%)."""
    spent, budget = float(spent), float(budget)
    if budget <= 0:
        return {"budget": 0, "spent": round(spent, 2), "remaining": 0, "pct": 0, "level": "none"}
    used = pct(spent, budget)
    level = "over" if spent > budget else "warn" if used >= 80 else "ok"
    return {"budget": round(budget, 2), "spent": round(spent, 2),
            "remaining": round(budget - spent, 2), "pct": round(used, 2), "level": level}


# ---------------------------------------------------------------- currency
BASE_CURRENCY = "USD"
CURRENCIES = {"USD": "US Dollar", "INR": "Indian Rupee", "EUR": "Euro", "GBP": "British Pound",
              "JPY": "Japanese Yen", "AED": "UAE Dirham", "CAD": "Canadian Dollar",
              "AUD": "Australian Dollar", "SGD": "Singapore Dollar"}
# Used only when live rates cannot be fetched (1 USD = x).
FALLBACK_RATES = {"USD": 1.0, "INR": 83.5, "EUR": 0.92, "GBP": 0.79, "JPY": 150.0,
                  "AED": 3.6725, "CAD": 1.36, "AUD": 1.52, "SGD": 1.34}


def convert(amount, rate_from, rate_to):
    """Convert between two currencies given their per-USD rates."""
    return float(amount) / float(rate_from) * float(rate_to)
