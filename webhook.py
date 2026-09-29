"""Webhook that MacroDroid posts bank SMS to.

Run: uvicorn api:app --host 0.0.0.0 --port 8000
"""
import hmac
import json
import os
import re

from fastapi import FastAPI, HTTPException, Request

import db
from sms_parser import AMT, categorize, parse_sms

TOKEN = os.environ.get("COOKED_TOKEN")
if not TOKEN:
    raise RuntimeError("Set COOKED_TOKEN before starting the API (any long random string).")

db.init_db()
app = FastAPI(title="Am I cooked? webhook")


async def _sms_text(request: Request) -> str:
    """Accepts plain text, or JSON like {"sms": "..."}."""
    raw = (await request.body()).decode("utf-8", errors="replace").strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            return str(data.get("sms") or data.get("message") or data.get("text") or raw)
        except ValueError:
            pass  # SMS had a stray quote that broke the JSON; the parser copes with raw text
    return raw


@app.get("/")
def health():
    return {"ok": True}


@app.post("/")
async def log_transaction(request: Request):
    supplied = request.headers.get("x-token") or request.query_params.get("token") or ""
    if not hmac.compare_digest(supplied, TOKEN):
        raise HTTPException(status_code=401, detail="bad token")

    text = await _sms_text(request)
    today = db.today_ist()
    parsed = parse_sms(text, today)

    if parsed is None:
        # has a rupee amount but we couldn't read it -> keep it for the sidebar inbox
        if AMT.search(text) and not re.search(r"otp", text, re.I):
            db.add_unparsed(text)
            return {"status": "unparsed"}
        return {"status": "ignored"}

    category = categorize(parsed["merchant"], parsed["direction"])
    if db.recent_duplicate(parsed["date"], parsed["merchant"], parsed["amount"], parsed["direction"]):
        return {"status": "duplicate"}
    ok = db.add_transaction(
        parsed["date"], parsed["merchant"], parsed["amount"],
        direction=parsed["direction"], category=category, upi_ref=parsed["upi_ref"],
    )
    if not ok:
        return {"status": "duplicate"}

    matched = False
    if parsed["direction"] == "credit":
        # money you were waiting for just landed: stop counting it as "expected"
        matched = db.match_expected(parsed["amount"], parsed["date"].strftime("%Y-%m"))

    return {"status": "logged", "merchant": parsed["merchant"], "amount": parsed["amount"],
            "direction": parsed["direction"], "category": category, "matched_expected": matched}
