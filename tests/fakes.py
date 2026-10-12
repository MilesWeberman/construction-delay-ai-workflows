"""Fake LLM answers for the sample inbox, shared by end-to-end tests."""

from datetime import date

from delay_ai.events import EMAIL_RECEIVED, MATERIAL_ORDERED, EventStore
from delay_ai.extraction import EmailExtraction, ExtractedItem
from delay_ai.ingestion import make_email_handler
from delay_ai.linking import LinkSuggestion, make_link_handler


def item(po, description, delivery, quantity=None, unit=None):
    return ExtractedItem(
        po_number=po,
        description=description,
        quantity=quantity,
        unit=unit,
        delivery_date=delivery,
    )


def extraction(kind, items, supplier=None, reason=None, confidence=0.95):
    return EmailExtraction(
        kind=kind, supplier=supplier, items=items, reason=reason, confidence=confidence
    )


# What a well-behaved LLM returns for each sample email.
CANNED = {
    "order-northgate-001@northgate-supplies.example": extraction(
        "order_confirmation",
        [
            item("PO-24101", "Precast concrete piles", date(2026, 11, 11), 120, "nr"),
            item("PO-24103", "Rebar and mesh", date(2026, 12, 2), 42, "t"),
            item("PO-24120", "Roof membrane and insulation", date(2027, 3, 17), 650, "m2"),
            item("PO-24150", "Plasterboard and metal studs", date(2027, 5, 19), 4200, "m2"),
            item("PO-24190", "Block paving and landscaping", date(2027, 3, 31), 1, "lot"),
            item("PO-24171", "Sanitaryware", date(2027, 6, 16), 60, "sets"),
            item("PO-24180", "LVT floor finishes", date(2027, 7, 14), 3100, "m2"),
        ],
        supplier="Northgate Building Supplies",
    ),
    "order-pennine-001@pennine-steel.example": extraction(
        "order_confirmation",
        [
            item("PO-24110", "Structural steel frame", date(2026, 12, 29), 310, "t"),
            item("PO-24111", "Composite metal decking", date(2027, 1, 27), 2600, "m2"),
        ],
        supplier="Pennine Steel Fabrications Ltd",
    ),
    "order-clearview-001@clearview-glazing.example": extraction(
        "order_confirmation",
        [
            item("PO-24130", "Unitised curtain wall panels", date(2027, 3, 3), 140, "nr"),
            item("PO-24131", "Aluminium windows", date(2027, 3, 3), 96, "nr"),
        ],
        supplier="Clearview Glazing Systems",
    ),
    "order-airevalley-001@airevalley-me.example": extraction(
        "order_confirmation",
        [item("PO-24140", "MEP first fix", date(2027, 4, 14), 1, "lot")],
        supplier="Aire Valley M&E Ltd",
    ),
    "order-apex-001@apex-lifts.example": extraction(
        "order_confirmation",
        [item("PO-24160", "Passenger lifts", date(2027, 3, 3), 2, "nr")],
        supplier="Apex Lifts UK Ltd",
    ),
    "order-calder-001@calder-kitchens.example": extraction(
        "order_confirmation",
        [item("PO-24170", "Kitchen units", date(2027, 6, 16), 48, "sets")],
        supplier="Calder Kitchens",
    ),
    "news-0915@northgate-supplies.example": extraction("not_relevant", []),
    "update-001@calder-kitchens.example": extraction(
        "delivery_change",
        [item(None, "Kitchen units", date(2027, 6, 23))],
        reason="Haulier lost a vehicle slot",
    ),
    "update-002@apex-lifts.example": extraction(
        "delivery_change",
        [item("PO-24160", "Passenger lifts", date(2027, 3, 24))],
        reason="Component shortage",
    ),
    "update-003@pennine-steel.example": extraction(
        "delivery_change",
        [item("PO-24110", "Structural steel", date(2027, 1, 12))],
        reason="Mill delay",
    ),
    "update-004@northgate-supplies.example": extraction(
        "delivery_confirmation",
        [item("PO-24150", "Plasterboard and metal studs", date(2027, 5, 19))],
    ),
    "update-005@clearview-glazing.example": extraction(
        "possible_delay", [item(None, "Windows", None)], confidence=0.5
    ),
}


def fake_extract(email, facts, known):
    return CANNED[email.message_id]


# The activity each sample PO is really for.
TRUE_LINKS = {
    "PO-24101": "A02",
    "PO-24103": "A03",
    "PO-24120": "A08",
    "PO-24150": "A13",
    "PO-24190": "A18",
    "PO-24171": "A16",
    "PO-24180": "A17",
    "PO-24110": "A05",
    "PO-24111": "A06",
    "PO-24130": "A09",
    "PO-24131": "A10",
    "PO-24140": "A12",
    "PO-24160": "A14",
    "PO-24170": "A16",
}


def fake_link(material, activities, schedule):
    return LinkSuggestion(
        activity_id=TRUE_LINKS[material.po_number], confidence=0.9, rationale="fake"
    )


def base_handlers(store: EventStore, activities, schedule) -> dict:
    return {
        EMAIL_RECEIVED: make_email_handler(store, fake_extract),
        MATERIAL_ORDERED: make_link_handler(activities, schedule, fake_link),
    }
