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
