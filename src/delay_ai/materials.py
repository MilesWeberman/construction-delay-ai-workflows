"""The materials table, rebuilt from events so every row traces back to an email."""

from datetime import date

from delay_ai.events import (
    DELIVERY_DATE_CHANGED,
    LINK_SUGGESTED,
    MATERIAL_LINKED,
    MATERIAL_ORDERED,
    Event,
)
from delay_ai.models import Material


def build_materials(events: list[Event]) -> list[Material]:
    materials: dict[str, Material] = {}
    for event in events:
        if event.type == MATERIAL_ORDERED:
            material = Material.model_validate(event.payload["material"])
            materials[material.po_number] = material
        elif event.type == DELIVERY_DATE_CHANGED:
            po_number = event.payload["po_number"]
            materials[po_number] = materials[po_number].model_copy(
                update={"planned_delivery": date.fromisoformat(event.payload["new_delivery"])}
            )
        elif event.type == MATERIAL_LINKED:
            po_number = event.payload["po_number"]
            materials[po_number] = materials[po_number].model_copy(
                update={"activity_id": event.payload["activity_id"]}
            )
    return list(materials.values())


def pending_link_suggestions(events: list[Event]) -> list[Event]:
    """The latest suggestion for each material a planner still has to link."""
    unlinked = {m.po_number for m in build_materials(events) if m.activity_id is None}
    latest = {e.payload["po_number"]: e for e in events if e.type == LINK_SUGGESTED}
    return [e for po_number, e in latest.items() if po_number in unlinked]
