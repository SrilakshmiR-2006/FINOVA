import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from finance import age_from_dob, available_balance, finance_score, password_is_strong, totals


def test_balance():
    t = totals([{"type": "income", "amount": 1000}, {"type": "expense", "amount": 300},
                {"type": "saving", "amount": 200}])
    assert available_balance(t) == 500


def test_score_88():
    assert finance_score({"income": 1000, "expense": 500, "saving": 200}, 20) == 88


def test_score_zero_no_income():
    assert finance_score({"income": 0, "expense": 100, "saving": 0}, 20) == 0


def test_score_zero_all_spent():
    assert finance_score({"income": 1000, "expense": 1000, "saving": 0}, 20) == 0


def test_age():
    assert age_from_dob("2000-11-18", date(2026, 11, 17)) == 25
    assert age_from_dob("2000-11-17", date(2026, 11, 17)) == 26


def test_password():
    assert password_is_strong("Finova#2026")
    assert not password_is_strong("finova2026")
    assert not password_is_strong("Fin#1")


from finance import budget_status, convert, goal_progress, investment_metrics, portfolio_summary


def test_investment_metrics():
    m = investment_metrics({"quantity": 10, "buy_price": 100, "current_price": 125})
    assert m == {"invested": 1000, "value": 1250, "pl": 250, "return_pct": 25.0}
    loss = investment_metrics({"quantity": 2, "buy_price": 50, "current_price": 40})
    assert loss["pl"] == -20 and loss["return_pct"] == -20.0


def test_portfolio_return_is_weighted():
    s = portfolio_summary([
        {"asset_type": "Stocks", "quantity": 1, "buy_price": 1000, "current_price": 1100},  # +10%
        {"asset_type": "Gold", "quantity": 1, "buy_price": 100, "current_price": 50},       # -50%
    ])
    assert s["invested"] == 1100 and s["value"] == 1150 and s["pl"] == 50
    assert s["return_pct"] == round(50 / 1100 * 100, 2)
    assert s["allocation"][0]["asset_type"] == "Stocks"
    assert round(sum(a["pct"] for a in s["allocation"])) == 100


def test_empty_portfolio():
    assert portfolio_summary([])["return_pct"] == 0


def test_goal_progress():
    assert goal_progress(1000, 250) == {"saved": 250, "remaining": 750, "pct": 25.0, "completed": False}
    done = goal_progress(1000, 1200)
    assert done["remaining"] == 0 and done["pct"] == 100 and done["completed"]


def test_budget_alerts():
    assert budget_status(100, 0)["level"] == "none"
    assert budget_status(500, 1000)["level"] == "ok"
    assert budget_status(800, 1000)["level"] == "warn"
    over = budget_status(1200, 1000)
    assert over["level"] == "over" and over["remaining"] == -200


def test_convert():
    assert convert(100, 1, 83.5) == 8350
    assert round(convert(8350, 83.5, 1), 6) == 100
