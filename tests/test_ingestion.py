from datetime import UTC, date, datetime

from fakes import extraction, fake_extract, item

from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    EMAIL_IGNORED,
    EMAIL_RECEIVED,
    NEEDS_REVIEW,
    EventStore,
)
from delay_ai.extraction import apply_rules
from delay_ai.ingestion import decide, make_email_handler
from delay_ai.materials import build_materials
from delay_ai.models import Email, Material
from delay_ai.orchestrator import Orchestrator, ingest_emails


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
