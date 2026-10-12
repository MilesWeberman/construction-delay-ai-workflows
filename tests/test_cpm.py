from datetime import date

import pytest

from delay_ai.cpm import add_working_days, compute_schedule, working_days_between
from delay_ai.loaders import load_schedule
from delay_ai.models import Activity

START = date(2026, 11, 2)  # a Monday


def test_add_working_days_skips_weekends():
    friday = date(2026, 11, 6)
    assert add_working_days(friday, 1) == date(2026, 11, 9)


def test_working_days_between_is_inverse_of_add():
    assert working_days_between(START, add_working_days(START, 37)) == 37
    assert working_days_between(add_working_days(START, 5), START) == -5


def test_sample_schedule(sample_dir):
    schedule = compute_schedule(load_schedule(sample_dir / "schedule.csv"), START)
    acts = schedule.activities

    assert schedule.duration_days == 210
    assert schedule.finish_date == date(2027, 8, 23)
    assert schedule.critical_path() == [
        "A01", "A02", "A03", "A04", "A05", "A06", "A09",
        "A11", "A12", "A13", "A16", "A17", "A19", "A20",
    ]  # fmt: skip
    assert acts["A14"].total_float == 85  # lifts
    assert acts["A10"].total_float == 15  # windows
    assert schedule.start_of("A05") == date(2027, 1, 4)


def test_earliest_start_constraint_pushes_activity_and_successors():
    activities = [
        Activity(id="A", name="A", trade="t", duration_days=5),
        Activity(id="B", name="B", trade="t", duration_days=5, predecessors=["A"]),
    ]
    schedule = compute_schedule(activities, START, earliest_start={"A": 3})
    assert schedule.activities["B"].early_start == 8
    assert schedule.duration_days == 13


def test_cycle_is_rejected():
    activities = [
        Activity(id="A", name="A", trade="t", duration_days=1, predecessors=["B"]),
        Activity(id="B", name="B", trade="t", duration_days=1, predecessors=["A"]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        compute_schedule(activities, START)
