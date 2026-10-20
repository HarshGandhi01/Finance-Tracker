from datetime import date
import pytest
from sms_parser import parse_sms


@pytest.mark.parametrize("sms,merchant,direction,amount", [
    ("ICICI Bank Acct XX123 debited Rs 20.00 on 12-Oct-26; CHAI STALL credited. UPI:123456789012",
     "Chai Stall", "debit", 20),
    ("INR 2000.00 credited to your account from ALEX on 12-Oct-26. Ref 123456789013",
     "Alex", "credit", 2000),
    ("INR 450.00 spent using ICICI Bank Card XX1234 on 12-Oct-26 on SWIGGY. Avl Limit 2000",
     "Swiggy", "debit", 450),
    ("INR 450.00 spent using ICICI Bank Card XX1234 on 12/10/2026 at SWIGGY. Avl Limit 2000",
     "Swiggy", "debit", 450),
    ("Rs 80 paid to CAMPUS STORE on 12-Oct-26.", "Campus Store", "debit", 80),
])
def test_supported_templates(sms, merchant, direction, amount):
    parsed = parse_sms(sms, date(2026, 10, 20))
    assert (parsed["merchant"], parsed["direction"], parsed["amount"]) == (merchant, direction, amount)
    assert parsed["date"] == date(2026, 10, 12)


@pytest.mark.parametrize("sms", [
    "OTP 123456 for INR 450 purchase using ICICI Bank Card.",
    "Your account will be debited INR 450 on 12-Oct-26.",
])
def test_non_transactions_are_ignored(sms):
    assert parse_sms(sms, date(2026, 10, 20)) is None
