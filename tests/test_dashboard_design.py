import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
from views import budget_status, food_caption


@pytest.mark.parametrize("allowance,status", [
    (-10, "Cooked"), (349.99, "Cooked"), (350, "Tight"),
    (437.49, "Tight"), (437.50, "Comfortable"),
])
def test_status_thresholds(allowance, status):
    assert budget_status(allowance) == status


@pytest.mark.parametrize("silo,caption", [
    (999, "₹1 over today · covered by silo"),
    (-1, "₹1 over today · silo is negative"),
])
def test_food_caption_explains_overspending(silo, caption):
    assert food_caption({"today_food_spend": 351, "food_silo_after_today": silo}) == caption
