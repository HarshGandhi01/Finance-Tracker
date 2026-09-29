# --- PROJECT STATE & HANDOVER LOG ---
# Last Updated: 2026-09-30
# Context: The user is building "Am I Cooked?", a personal finance tracker.

## Current Implementation State
- Tech Stack: Streamlit, SQLAlchemy, Neon Postgres, FastAPI (Backend).
- Security: 
    - Secrets moved to environment variables (DATABASE_URL, COOKED_TOKEN).
    - Git history wiped to remove leaked secrets.
    - .gitignore hardened.
- Deployment:
    - Frontend: Streamlit Cloud.
    - Backend: Render.com (running `index.py` via `uvicorn`).
- Integration: MacroDroid (Android) $\rightarrow$ Render Webhook $\rightarrow$ Neon DB $\rightarrow$ Streamlit.

## Recent Changes (Current Sprint)
1. **Food Silo Logic**:
    - Implemented a rollover system: yesterday's food savings are added to a persistent silo.
    - Added `update_food_silo` to `db.py` and triggered it in `app.py`.
    - Fixed a bug where the silo updated based on *today's* spend instead of *yesterday's*.
    - Added a "Reset Food Silo to 0" button in the UI.
2. **Math Correction**:
    - Fixed "Safe to spend" calculation: now `Actual Balance - Reserved Funds`.
    - Removed "Expected Income" from safe spending to prevent inflated numbers.
3. **Backend/Deployment**:
    - Fixed `ModuleNotFoundError: No module named 'psycopg'` by updating `requirements.txt` to `psycopg[binary]`.
    - Fixed Render start command to `python -m uvicorn index:app --host 0.0.0.0 --port 10000`.
    - Fixed a `SyntaxError` caused by escaped quotes in docstrings.

## Pending/Critical Issues
- **Sync Issues**: The user is reporting that the website doesn't reflect changes even after deployment. This is likely due to Streamlit Cloud caching or a failure to reboot the app after `db.py` updates.
- **Webhook verification**: Manual tests show the webhook is alive, but the `sms_parser` might be too strict for certain bank formats.

## Instructions for Next AI
- If the user reports a `SyntaxError` or "numbers not updating", check for:
    1. Escaped quotes (`\"\"\"`) in `db.py` (these cause crashes on some servers).
    2. Streamlit Cloud caching (suggest a full app reboot).
- Ensure any changes to `db.py` are reflected in the `requirements.txt` if new libraries are added.
- Always verify the `COOKED_TOKEN` is consistent across Render, Streamlit, and MacroDroid.
