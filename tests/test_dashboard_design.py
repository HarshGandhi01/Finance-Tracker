import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
from views import budget_status, food_caption, debits_to_reach, days_to_save


@pytest.mark.parametrize("allowance,status", [
    (-10, "Cooked"), (349.99, "Cooked"), (350, "Tight"),
    (437.49, "Tight"), (437.50, "Comfortable"),
])
def test_status_thresholds(allowance, status):
    assert budget_status(allowance) == status


@pytest.mark.parametrize("silo,caption", [
    (999, "₹1 over today · covered by savings"),
    (-1, "₹1 over today · savings go negative"),
])
def test_food_caption_explains_overspending(silo, caption):
    assert food_caption({"today_food_spend": 351, "food_silo_after_today": silo,
                         "target_daily": 350}) == caption


def test_debits_to_reach_finds_fewest_biggest_reversals():
    # allowance 100/day (1000/10). Reversing the ₹1000 alone lifts it to 200/day.
    assert debits_to_reach([300, 1000, 500], 1000, 10, 200) == (1, 1000)
    assert debits_to_reach([300, 1000, 500], 1000, 10, 250) == (2, 1500)
    assert debits_to_reach([300, 1000, 500], 1000, 10, 1000) is None  # unreachable
    assert debits_to_reach([], 1000, 10, 50) is None


def test_days_to_save_estimates_when_savings_cover_a_payment():
    assert days_to_save(3000, 500, 150) == 17   # ceil(2500/150)
    assert days_to_save(1000, 1000, 150) == 0    # already covered
    assert days_to_save(1000, 1200, 150) == 0
    assert days_to_save(5000, 0, 0) is None       # not banking anything
    assert days_to_save(5000, 0, -20) is None     # over budget
