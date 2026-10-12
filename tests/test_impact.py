from datetime import date

import pytest

from delay_ai.impact import assess_delivery_change
from delay_ai.loaders import load_schedule
from delay_ai.models import Material

START = date(2026, 11, 2)


def material(po, activity_id, delivery):
    return Material(
        po_number=po,
        description=po,
        supplier="s",
        supplier_email="s@example.com",
        planned_delivery=delivery,
        activity_id=activity_id,
    )


@pytest.fixture
def activities(sample_dir):
    return load_schedule(sample_dir / "schedule.csv")


@pytest.fixture
def materials():
    return [
        material("PO-24110", "A05", date(2026, 12, 29)),  # steel
        material("PO-24160", "A14", date(2027, 3, 3)),  # lifts
        material("PO-24170", "A16", date(2027, 6, 16)),  # kitchens
    ]


def test_steel_delay_slips_project(activities, materials):
    impact = assess_delivery_change(activities, materials, START, "PO-24110", date(2027, 1, 12))
    # delivery moves 10 working days, but 3 days of lead time absorb part of it
    assert impact.float_before_days == 0
    assert impact.project_slip_days == 7
    assert impact.new_finish == date(2027, 9, 1)
    assert "A20" in impact.delayed_activities


def test_lift_delay_absorbed_by_float(activities, materials):
    impact = assess_delivery_change(activities, materials, START, "PO-24160", date(2027, 3, 24))
    assert impact.activity_slip_days == 13
    assert impact.project_slip_days == 0
    assert impact.delayed_activities == ["A14"]


def test_kitchen_delay_slips_project(activities, materials):
    impact = assess_delivery_change(activities, materials, START, "PO-24170", date(2027, 6, 23))
    assert impact.project_slip_days == 3


def test_unlinked_material_is_rejected(activities):
    unlinked = [material("PO-1", None, date(2027, 1, 1))]
    with pytest.raises(ValueError, match="not linked"):
        assess_delivery_change(activities, unlinked, START, "PO-1", date(2027, 2, 1))
