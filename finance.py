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
