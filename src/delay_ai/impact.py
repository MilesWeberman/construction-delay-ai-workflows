"""What a change in a material's delivery date does to the schedule."""

from datetime import date

from pydantic import BaseModel

from delay_ai.cpm import Schedule, compute_schedule, working_days_between
from delay_ai.models import Activity, Material


class DeliveryImpact(BaseModel):
    po_number: str
    activity_id: str
    old_delivery: date
    new_delivery: date
    float_before_days: int  # slack the activity had before the change
    activity_slip_days: int
    project_slip_days: int
    old_finish: date
    new_finish: date
    delayed_activities: list[str]  # every activity whose start moved later


def material_constraints(materials: list[Material], start_date: date) -> dict[str, int]:
    """Earliest start per activity: the working day after its last material arrives."""
    constraints: dict[str, int] = {}
    for material in materials:
        if material.activity_id:
            ready = working_days_between(start_date, material.planned_delivery) + 1
            constraints[material.activity_id] = max(constraints.get(material.activity_id, 0), ready)
    return constraints


def schedule_with_materials(
    activities: list[Activity], materials: list[Material], start_date: date
) -> Schedule:
    return compute_schedule(activities, start_date, material_constraints(materials, start_date))


def assess_delivery_change(
    activities: list[Activity],
    materials: list[Material],
    start_date: date,
    po_number: str,
    new_delivery: date,
) -> DeliveryImpact:
    material = next((m for m in materials if m.po_number == po_number), None)
    if material is None:
        raise ValueError(f"Unknown PO: {po_number}")
    if material.activity_id is None:
        raise ValueError(f"{po_number} is not linked to an activity yet")

    changed = [
        m.model_copy(update={"planned_delivery": new_delivery}) if m.po_number == po_number else m
        for m in materials
    ]
    before = schedule_with_materials(activities, materials, start_date)
    after = schedule_with_materials(activities, changed, start_date)

    def slip(activity_id: str) -> int:
        return (
            after.activities[activity_id].early_start - before.activities[activity_id].early_start
        )

    return DeliveryImpact(
        po_number=po_number,
        activity_id=material.activity_id,
        old_delivery=material.planned_delivery,
        new_delivery=new_delivery,
        float_before_days=before.activities[material.activity_id].total_float,
        activity_slip_days=slip(material.activity_id),
        project_slip_days=after.duration_days - before.duration_days,
        old_finish=before.finish_date,
        new_finish=after.finish_date,
        delayed_activities=[a.id for a in activities if slip(a.id) > 0],
    )
