"""One-off: python seed.py  ->  balance ₹5,000 now, ₹2,000 expected on the 25th."""
from datetime import date
import db

db.init_db()
db.set_balance(5000)
t = date.today()
db.add_expected(date(t.year, t.month, 25), "Money from home", 2000)
print("Seeded: balance ₹5,000, ₹2,000 expected on the 25th.")
