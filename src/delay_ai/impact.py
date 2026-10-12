"""What a change in a material's delivery date does to the schedule."""

from collections.abc import Callable
from datetime import date

from pydantic import BaseModel

from delay_ai.cpm import Schedule, compute_schedule, working_days_between
from delay_ai.events import DELAY_ASSESSED, DELIVERY_DATE_CHANGED, Emit, Event, EventStore
from delay_ai.materials import build_materials
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


def assess_unassessed_changes(
    po_number: str, events: list[Event], activities: list[Activity], start_date: date
) -> list[Emit]:
    """Assess every delivery change for this PO that has not been assessed yet.

    Runs when a change arrives and again when the material gets linked, so a
    change that arrived before the link is picked up then.
    """
    links = {m.po_number: m.activity_id for m in build_materials(events)}
    if links.get(po_number) is None:
        return []  # wait until a planner links it
    assessed = {e.payload["change_event"] for e in events if e.type == DELAY_ASSESSED}
    emits = []
    for change in events:
        if (
            change.type != DELIVERY_DATE_CHANGED
            or change.payload["po_number"] != po_number
            or change.id in assessed
        ):
            continue
        # Delivery dates as they were just before this change, with today's links.
        before = [
            m.model_copy(update={"activity_id": links.get(m.po_number)})
            for m in build_materials([e for e in events if e.id < change.id])
        ]
        impact = assess_delivery_change(
            activities,
            before,
            start_date,
            po_number,
            date.fromisoformat(change.payload["new_delivery"]),
        )
        emits.append(
            Emit(DELAY_ASSESSED, {"change_event": change.id, **impact.model_dump(mode="json")})
        )
    return emits


def make_impact_handler(
    store: EventStore, activities: list[Activity], start_date: date
) -> Callable[[Event], list[Emit]]:
    """Handles both DeliveryDateChanged and MaterialLinked."""

    def handle(event: Event) -> list[Emit]:
        return assess_unassessed_changes(
            event.payload["po_number"], store.all(), activities, start_date
        )

    return handle
