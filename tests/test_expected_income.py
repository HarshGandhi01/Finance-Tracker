from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
import db


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    with patch.object(db, "ENGINE", engine):
        db._INITED = False
        db.init_db()
        yield
    engine.dispose()
    db._INITED = False


@pytest.mark.parametrize("day", [20, 25, 30])
def test_match_inside_inclusive_window(database, day):
    db.add_expected("2026-10-25", "Home", 2000)
    assert db.match_expected(2000, date(2026, 10, day))
    assert db.get_expected("2026-10") == []


@pytest.mark.parametrize("day", [19, 31])
def test_no_match_outside_window(database, day):
    db.add_expected("2026-10-25", "Home", 2000)
    assert not db.match_expected(2000, date(2026, 10, day))
    assert len(db.get_expected("2026-10")) == 1


def test_closest_date_wins_and_different_amount_stays(database):
    for day, label, amount in [(22, "Earlier", 2000), (26, "Closest", 2000), (25, "Different", 2001)]:
        db.add_expected(f"2026-10-{day}", label, amount)
    assert db.match_expected(2000, date(2026, 10, 25))
    assert [e["label"] for e in db.get_expected("2026-10")] == ["Earlier", "Different"]
