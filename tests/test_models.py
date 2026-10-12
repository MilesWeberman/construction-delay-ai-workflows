from datetime import date

from delay_ai.models import Activity, Material


def test_activity_defaults_to_no_predecessors():
    activity = Activity(id="A01", name="Site set-up", trade="Preliminaries", duration_days=10)
    assert activity.predecessors == []


def test_material_is_unlinked_by_default():
    material = Material(
        po_number="PO-1",
        description="Precast piles",
        supplier="Northgate",
        supplier_email="orders@northgate.example",
        planned_delivery=date(2026, 11, 11),
    )
    assert material.activity_id is None
