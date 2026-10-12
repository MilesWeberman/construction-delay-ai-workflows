"""The current plan: the schedule export plus the options planners have chosen."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from delay_ai.events import OPTION_CHOSEN, Event
from delay_ai.models import Activity, Material

MAX_SHORTEN = 0.3  # share of an activity's duration that acceleration can save
# Earlier deliveries only count once the supplier confirms them by email.
PLAN_EDITS = {"remove_dependency", "shorten"}


class Edit(BaseModel):
    type: Literal["remove_dependency", "shorten", "change_delivery"]
    activity_id: str | None = Field(description="For remove_dependency and shorten")
    predecessor_id: str | None = Field(description="For remove_dependency: the link to drop")
    days: int | None = Field(description="For shorten: working days to take off")
    po_number: str | None = Field(description="For change_delivery")
    new_delivery: date | None = Field(
        description="For change_delivery: the earlier date to ask for"
    )


def apply_edits(
    edits: list[Edit], activities: list[Activity], materials: list[Material], today: date
) -> tuple[list[Activity], list[Material], list[str]]:
    """Apply edits to copies of the plan. Returns the new plan and any problems."""
    acts = {a.id: a.model_copy(deep=True) for a in activities}
    mats = {m.po_number: m.model_copy() for m in materials}
    problems = []
    for edit in edits:
        activity = acts.get(edit.activity_id or "")
        if edit.type == "remove_dependency":
            if activity is None or edit.predecessor_id not in activity.predecessors:
                problems.append(f"{edit.activity_id} does not follow {edit.predecessor_id}")
            else:
                activity.predecessors.remove(edit.predecessor_id)
        elif edit.type == "shorten":
            limit = int(activity.duration_days * MAX_SHORTEN) if activity else 0
            if activity is None or not edit.days or not 0 < edit.days <= limit:
                problems.append(f"Cannot shorten {edit.activity_id} by {edit.days} (max {limit})")
            else:
                activity.duration_days -= edit.days
        elif edit.type == "change_delivery":
            material = mats.get(edit.po_number or "")
            if material is None or edit.new_delivery is None:
                problems.append(f"Unknown order {edit.po_number}")
            elif not today <= edit.new_delivery < material.planned_delivery:
                problems.append(
                    f"{edit.po_number}: new date must be from {today} and before "
                    f"{material.planned_delivery}"
                )
            else:
                mats[material.po_number] = material.model_copy(
                    update={"planned_delivery": edit.new_delivery}
                )
    return list(acts.values()), list(mats.values()), problems


def current_activities(base: list[Activity], events: list[Event]) -> list[Activity]:
    activities = base
    for event in events:
        if event.type == OPTION_CHOSEN:
            edits = [Edit.model_validate(e) for e in event.payload["option"]["edits"]]
            edits = [e for e in edits if e.type in PLAN_EDITS]
            # Already validated when proposed; skip anything the plan has since outgrown.
            activities, _, _ = apply_edits(edits, activities, [], date.min)
    return activities
