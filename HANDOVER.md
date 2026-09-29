# --- PROJECT STATE & HANDOVER LOG ---
# Last Updated: 2026-09-29
# Context: The user is building "Am I Cooked?", a personal finance tracker.

## Current Implementation State
- Tech Stack: Streamlit, SQLAlchemy, Neon Postgres.
- Security: 
    - Moved secrets to environment variables (DATABASE_URL, COOKED_TOKEN).
    - Hardcoded credentials removed from code.
    - Git history wiped to remove leaked secrets.
    - .gitignore hardened.
    - XSS prevented by removing `unsafe_allow_html=True` in the ledger.
- Integration: Tasker (Android) is configured to POST SMS data to `/log`.

## Recent Changes (Current Sprint)
1. Fixed `OperationalError` by correctly formatting TOML secrets in Streamlit Cloud.
2. Resolved an `IndentationError` in `dashboard/app.py`.
3. Removed redundant `env.txt` and duplicate `app.py` files.
4. Implemented "Clean" markdown rendering for transactions to replace unsafe HTML.

## Pending Feature: "Food Silo" Logic
The user wants a dynamic food budget:
- Daily target: ₹350.
- If spend < ₹350: The remainder goes into "Additional Food" (a virtual silo).
- If spend > ₹350: Use the daily budget first, then pull the deficit from "Additional Food".
- This requires persistent state for the 'Additional Food' balance.

## Instructions for Next AI
- Review `db.py` `compute_metrics` to implement the Food Silo.
- The state should be stored in the `settings` table as `food_silo_balance`.
- Ensure calculations for `food_remaining_today` reflect this silo logic.
- Maintain the high security bar (no hardcoded secrets).
