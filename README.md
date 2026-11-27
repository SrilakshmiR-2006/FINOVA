# FINOVA — Flask + HTML/CSS/JS version

Finance analytics & budget tracking: income / expenses / savings, finance score,
charts, calendar, monthly & yearly budgets with alerts, investment portfolio,
financial goals, currency conversion, profile and admin overview. Same screens, rules and look as the original.

## Run in VS Code
```
python -m venv .venv
.venv\Scripts\activate        # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app.py                 # http://localhost:8080
python -m pytest tests        # optional: run the finance-rule tests
```

## Files
- `app.py` — routes, auth, SQLite, JSON API    - `finance.py` — money math + password rules
- `templates/` — HTML pages                      - `static/css/style.css` — design tokens & components
- `static/js/` — common.js, dashboard.js         - `finova.db` — created automatically on first run

## Notes
- The first account created becomes admin (same as the original). Admin sign-in uses the "Admin" tab.
- Forgot password: there is no mail server locally, so the reset link is printed in the terminal
  and shown on the page in debug mode (set `FINOVA_SHOW_RESET_LINK=1` to show it otherwise).
- Google sign-in needs OAuth credentials, so that button only shows a notice; email + password works fully.
- Put your real logo at `static/img/finova-logo.jpg` — it is used automatically (an SVG fallback is included).
- Charts use Chart.js and fonts come from Google Fonts (internet needed for those two).
- Set `FINOVA_SECRET` to a long random string before deploying anywhere public.

## New in this version
- **Investments & Goals page** (`/wealth`): add / edit / delete holdings (Stocks, Mutual Funds, Gold,
  Fixed Deposits, Bonds, Crypto, Real Estate, Other), update current prices, see invested amount,
  current value, profit/loss and return % per holding and overall, plus an asset-allocation chart.
- **Goals**: name, target amount, target date; add or remove savings entries; saved / remaining /
  progress bar; edit and delete; a notification appears when a goal is completed.
- **Dashboard**: total expenses, monthly & yearly budget, remaining budget, budget alerts (80% and
  over budget), expense trends, portfolio value, returns, allocation and goal progress.
- **Currency switcher** in the header (USD, INR, EUR, GBP, JPY, AED, CAD, AUD, SGD). Amounts are stored
  in USD and converted with live rates (refreshed every 6 hours); built-in rates are used offline
  (or set `FINOVA_OFFLINE=1`). Your choice is saved to your account.
- Existing `finova.db` files are upgraded automatically on start — no data is lost.
