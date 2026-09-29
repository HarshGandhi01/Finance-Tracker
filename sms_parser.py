"""Turns a raw ICICI Bank SMS into {amount, direction, merchant, upi_ref, date}.

Tolerant on purpose: bank templates vary (UPI, card, IMPS). Anything that has an
amount but can't be understood is stored in the "unread messages" inbox instead of lost.
"""
import re
from datetime import date, datetime

AMT = re.compile(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
DEBIT = re.compile(r"\b(debited|spent|paid|sent|withdrawn|purchase)\b", re.I)
CREDIT = re.compile(r"\b(credited|received|deposited|refund(?:ed)?)\b", re.I)
SKIP = re.compile(r"\b(otp|one[- ]time|will be debited|is due|due on|requested|request from|offer|apply now)\b", re.I)
UPI_REF = re.compile(r"(?:UPI[:\s\-/]*|RRN[:\s\-]*|Ref(?:erence)?\.?\s*(?:No\.?|Number)?[:\s\-]*)(\d{9,12})", re.I)
TAIL = re.compile(r"\b(?:Call|SMS BLOCK|If not|To dispute|Not you|Avl|Available)\b", re.I)
END = r"(?=\s+(?:on|UPI|Ref|RRN|Avl|via|for|Call|If)\b|[.;,]|$)"
MERCHANT_DEBIT = [
    re.compile(r";\s*([^;.\n]+?)\s+credited", re.I),
    re.compile(r"\b(?:to|at)\s+(?:VPA\s+)?([A-Za-z0-9@&_ .*\-]+?)" + END, re.I),
]
MERCHANT_CREDIT = [
    re.compile(r"\b(?:from|by)\s+(?:VPA\s+)?([A-Za-z0-9@&_ .*\-]+?)" + END, re.I),
]
DATE_PATS = [
    (re.compile(r"(\d{1,2})[-/ ]([A-Za-z]{3})[-/ ](\d{2,4})"), "%d-%b-%y"),
    (re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})"), "%d-%m-%y"),
]

RULES = {
    "Food": ["shindi", "campus store", "malpe", "canteen", "mess", "swiggy", "zomato", "cafe",
             "hotel", "restaurant", "juice", "bakery", "tea", "chai", "biryani", "pizza"],
    "Protein": ["protein", "whey", "muscleblaze", "myprotein", "supplement"],
    "Laundry": ["laundry", "dhobi"],
    "Sports": ["turf", "sports", "cricket", "badminton", "gym"],
}


def categorize(merchant: str, direction: str) -> str:
    if direction == "credit":
        return "Other"
    m = merchant.lower()
    for cat, words in RULES.items():
        if any(w in m for w in words):
            return cat
    return "Other"


def _parse_date(text: str):
    for pat, _ in DATE_PATS:
        mt = pat.search(text)
        if not mt:
            continue
        d, mo, y = mt.groups()
        y = y[-2:] if len(y) == 4 else y
        for fmt in ("%d-%b-%y", "%d-%m-%y"):
            try:
                return datetime.strptime(f"{d}-{mo}-{y}", fmt).date()
            except ValueError:
                pass
    return None


def parse_sms(text: str, fallback_date: date):
    """Returns a dict, or None when this isn't a money movement."""
    if not text or SKIP.search(text):
        return None
    amt = AMT.search(text)
    d, c = DEBIT.search(text), CREDIT.search(text)
    if not amt or not (d or c):
        return None

    # whichever keyword shows up first is the direction
    # ("debited ... SHINDI credited" is a debit)
    if d and (not c or d.start() < c.start()):
        direction = "debit"
    else:
        direction = "credit"

    core = TAIL.split(text)[0]
    merchant = None
    for pat in (MERCHANT_DEBIT if direction == "debit" else MERCHANT_CREDIT):
        mt = pat.search(core)
        if mt:
            merchant = re.sub(r"\s+", " ", mt.group(1)).strip(" .-")
            break
    ref = UPI_REF.search(text)

    return dict(
        amount=float(amt.group(1).replace(",", "")),
        direction=direction,
        merchant=(merchant or "Unknown")[:60].title(),
        upi_ref=ref.group(1) if ref else None,
        date=_parse_date(text) or fallback_date,
    )
