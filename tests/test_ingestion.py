from datetime import UTC, date, datetime

from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    EMAIL_IGNORED,
    EMAIL_RECEIVED,
    NEEDS_REVIEW,
    EventStore,
)
from delay_ai.extraction import EmailExtraction, ExtractedItem, apply_rules
from delay_ai.ingestion import decide, make_email_handler
from delay_ai.materials import build_materials
from delay_ai.models import Email, Material
from delay_ai.orchestrator import Orchestrator, ingest_emails


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


def run_sample_inbox(sample_dir):
    store = EventStore()
    ingest_emails(FolderEmailSource(sample_dir / "emails"), store)
    Orchestrator(store, {EMAIL_RECEIVED: make_email_handler(store, fake_extract)}).run()
    return store.all()


def of_type(events, event_type):
    return [e for e in events if e.type == event_type]


def test_sample_inbox_builds_materials_table(sample_dir):
    events = run_sample_inbox(sample_dir)
    materials = {m.po_number: m for m in build_materials(events)}

    assert not [e for e in events if e.status == "failed"]
    assert len(materials) == 14
    assert materials["PO-24110"].planned_delivery == date(2027, 1, 12)  # after the delay
    assert materials["PO-24170"].supplier_email == "dispatch@calder-kitchens.example"


def test_sample_inbox_outcomes(sample_dir):
    events = run_sample_inbox(sample_dir)

    changes = {e.payload["po_number"]: e.payload for e in of_type(events, DELIVERY_DATE_CHANGED)}
    assert set(changes) == {"PO-24110", "PO-24160", "PO-24170"}
    assert changes["PO-24110"]["old_delivery"] == "2026-12-29"
    assert changes["PO-24110"]["date_source"] == "written_in_email"
    assert changes["PO-24170"]["matched_by"] == "only_order_from_sender"
    assert changes["PO-24170"]["date_source"] == "inferred_by_llm"

    assert [e.payload["po_number"] for e in of_type(events, DELIVERY_CONFIRMED)] == ["PO-24150"]
    assert len(of_type(events, EMAIL_IGNORED)) == 1

    (review,) = of_type(events, NEEDS_REVIEW)
    assert review.payload["source_email"] == "update-005@clearview-glazing.example"
    assert "Possible delay with no firm date" in review.payload["problems"]


def test_ingesting_twice_changes_nothing(sample_dir):
    store = EventStore()
    source = FolderEmailSource(sample_dir / "emails")
    orchestrator = Orchestrator(store, {EMAIL_RECEIVED: make_email_handler(store, fake_extract)})
    ingest_emails(source, store)
    orchestrator.run()
    count = len(store.all())

    ingest_emails(source, store)
    orchestrator.run()
    assert len(store.all()) == count


# Guards against a wrong LLM answer.

SENT = datetime(2026, 10, 12, 9, tzinfo=UTC)
STEEL = Material(
    po_number="PO-24110",
    description="Steel",
    supplier="Pennine",
    supplier_email="orders@pennine-steel.example",
    planned_delivery=date(2026, 12, 29),
)


def email(body, sender="orders@pennine-steel.example"):
    return Email(message_id="m1", sender=sender, subject="Update", sent_at=SENT, body=body)


def problems(e, result, materials):
    from_sender = [m for m in materials.values() if m.supplier_email == e.sender]
    emits = decide(e, apply_rules(e), result, materials, from_sender)
    assert [x.type for x in emits] == [NEEDS_REVIEW]
    return emits[0].payload["problems"]


def test_order_with_po_not_in_email_goes_to_review():
    e = email("Order confirmed for delivery 12/01/2027")
    result = extraction("order_confirmation", [item("PO-999", "Steel", date(2027, 1, 12))])
    assert "PO-999 is not written in the email" in problems(e, result, {})


def test_date_not_in_email_goes_to_review():
    e = email("PO-24110 now arrives 12/01/2027")
    result = extraction("delivery_change", [item("PO-24110", "Steel", date(2027, 1, 21))])
    assert any("not written in the email" in p for p in problems(e, result, {"PO-24110": STEEL}))


def test_update_from_another_supplier_goes_to_review():
    e = email("PO-24110 now arrives 12/01/2027", sender="someone@other.example")
    result = extraction("delivery_change", [item("PO-24110", "Steel", date(2027, 1, 12))])
    assert "PO-24110 belongs to a different supplier" in problems(e, result, {"PO-24110": STEEL})


def test_low_confidence_goes_to_review():
    e = email("PO-24110 now arrives 12/01/2027")
    result = extraction(
        "delivery_change", [item("PO-24110", "Steel", date(2027, 1, 12))], confidence=0.4
    )
    assert "Low confidence (40%)" in problems(e, result, {"PO-24110": STEEL})
