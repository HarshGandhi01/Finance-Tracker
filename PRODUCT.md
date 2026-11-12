# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A single known user: the owner. A young person in India who banks with ICICI and
checks the app on their phone throughout the day to decide, in one glance, whether
they can spend right now. There is one user, always — no second audience, no accounts.

## Product Purpose

"Am I cooked?" answers one question on demand: given everything spent this cycle, is
there safe money to spend today, or not. Bank SMS are ingested automatically so the
answer is always current without manual logging. Success is a trustworthy at-a-glance
verdict that the user acts on before spending.

## Positioning

The money facts come from the user's real ICICI transaction SMS, parsed automatically,
not from manual entry — so the spendable verdict reflects actual account activity in
near real time. On top of that sit cycle-based budgeting, a rolling food-budget "silo,"
poker net tracking, peer splits/repayments, "pay from savings" tagging, and a
big-payment planner — features a generic expense logger does not combine around a
single daily spend/don't-spend call.

## Operating Context

Pipeline: ICICI SMS → MacroDroid → FastAPI webhook (`index.py`, token-authenticated,
parsed by `sms_parser.py`) → SQLAlchemy store (`db.py`; Neon Postgres in production,
SQLite locally) → Streamlit dashboard (`dashboard/app.py`, Overview + Settings pages).
Deployed on Streamlit Community Cloud with no login (by design). Primary use is a quick
mobile glance; the dashboard is dark-themed.

Deploy reality future work must respect: the editable working copy lives at the OneDrive
path and is mirrored to a separate GitHub-linked location; a code change reaches the live
app only after commit → push → **rebooting** the Streamlit Cloud app (a push alone does
not restart it).

## Capabilities and Constraints

Capabilities: automatic SMS transaction ingestion; cycle-based budget with a daily
spendable verdict; rolling food-budget silo with daily rollover; peer expense splits and
repayments; vendor/merchant category rules; category management; poker buy-in/payout net
tracking; "pay from savings" tagging for big one-off buys; big-payment planner; CSV
export; transaction edit/reverse (e.g. failed-payment refunds).

Constraints: depends on the ICICI SMS format; single-tenant key-value `settings` table;
no authentication by design; Streamlit Community Cloud hosting; Python 3.12; tests run on
disposable SQLite. Real transaction data lives only in the production database, never in
the repository.

## Brand Commitments

Name: "Am I cooked?". Voice is blunt, casual, and self-aware — budget states read as
"cooked" / comfortable rather than clinical finance language. Dark dashboard is the
established look. Binding only as recorded here; no further visual direction is fixed.

## Evidence on Hand

- `README.md` — architecture, configuration, run/test instructions.
- `home_mobile.png` — a dashboard screenshot at mobile width.
- Live personal transaction data in the production Neon database (not in the repo, and not
  to be fabricated for demos).

No customers, testimonials, pricing, or press exist — this is a personal tool. Future work
must not invent them.

## Product Principles

- **One known user, no front door.** Optimize for the owner's daily glance; never add
  accounts, login, or onboarding.
- **The spendable verdict wins.** When features compete for attention, the "can I spend
  right now?" answer comes first; everything else is support.
- **Automatic over manual.** Money facts come from ingested SMS; manual entry is a
  fallback, not the default path.
- **Honest numbers over flattering ones.** The verdict shows real state even when it's bad
  (e.g. overdrawing savings stops the protection) — it never lies to feel good.
- **Phone-first glance.** The first and most common use is a quick check on mobile.
