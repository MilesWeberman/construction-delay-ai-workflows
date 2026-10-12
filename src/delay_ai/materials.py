"""The materials table, rebuilt from events so every row traces back to an email."""

from datetime import date

from delay_ai.events import DELIVERY_DATE_CHANGED, MATERIAL_ORDERED, Event
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
    return list(materials.values())
