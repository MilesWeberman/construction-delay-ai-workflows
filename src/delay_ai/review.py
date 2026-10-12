"""What a planner does by hand: settle an email the AI flagged, or mark a draft as sent."""

from datetime import date

from delay_ai.events import (
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    MESSAGE_SENT,
    NEEDS_REVIEW,
    REVIEW_RESOLVED,
    Emit,
    Event,
)
from delay_ai.materials import build_materials


def open_reviews(events: list[Event]) -> list[Event]:
    """NeedsReview events a planner hasn't settled yet."""
    settled = {e.payload["source_email"] for e in events if e.type == REVIEW_RESOLVED}
    return [
        e for e in events if e.type == NEEDS_REVIEW and e.payload["source_email"] not in settled
    ]


def enter_delivery_date(
    events: list[Event], email_id: str, po_number: str, new_date: date, today: date
) -> list[Emit]:
    """The planner reads a flagged email and enters the delivery date themselves."""
    materials = {m.po_number: m for m in build_materials(events)}
    if po_number not in materials:
        raise ValueError(f"Unknown order {po_number}")
    if new_date < today:
        raise ValueError("The delivery date can't be in the past")
    old = materials[po_number].planned_delivery
    source = {"po_number": po_number, "matched_by": "planner", "source_email": email_id}
    if new_date == old:
        fact = Emit(DELIVERY_CONFIRMED, source)
    else:
        fact = Emit(
            DELIVERY_DATE_CHANGED,
            {**source, "old_delivery": str(old), "new_delivery": str(new_date),
             "reason": "Entered by a planner", "date_source": "planner"},
        )  # fmt: skip
    return [fact, Emit(REVIEW_RESOLVED, {"source_email": email_id, "outcome": "date_entered"})]


def dismiss_review(email_id: str) -> Emit:
    return Emit(REVIEW_RESOLVED, {"source_email": email_id, "outcome": "dismissed"})


def mark_sent(message_id: str) -> Emit:
    """message_id is '<ActionPlanDrafted event id>:<index>'."""
    return Emit(MESSAGE_SENT, {"message_id": message_id})
