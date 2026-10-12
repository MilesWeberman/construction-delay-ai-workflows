from datetime import date

from fakes import extraction, item

from delay_ai.events import (
    CHAT_MESSAGE_RECEIVED,
    DELIVERY_DATE_CHANGED,
    MATERIAL_ORDERED,
    NEEDS_REVIEW,
    EventStore,
)
from delay_ai.ingestion import make_email_handler
from delay_ai.models import Material
from delay_ai.orchestrator import Orchestrator, ingest_chat

STEEL = Material(
    po_number="PO-24110",
    description="Structural steel",
    supplier="Pennine Steel Fabrications Ltd",
    supplier_email="orders@pennine-steel.example",
    planned_delivery=date(2027, 1, 12),
)
KITCHENS = STEEL.model_copy(
    update={
        "po_number": "PO-24170",
        "description": "Kitchen units",
        "supplier": "Calder Kitchens",
        "supplier_email": "dispatch@calder-kitchens.example",
        "planned_delivery": date(2027, 6, 23),
    }
)


def run_chat(text, answer):
    store = EventStore()
    for m in (STEEL, KITCHENS):
        store.append(MATERIAL_ORDERED, {"material": m.model_dump(mode="json")})
    seen = {}

    def extract(message, facts, known):
        seen["known"] = [m.po_number for m in known]
        return answer

    ingest_chat(text, "Priya Shah", store)
    handler = make_email_handler(store, extract)
    Orchestrator(store, {CHAT_MESSAGE_RECEIVED: handler}).run()
    return store.all(), seen


def test_chat_update_can_be_about_any_supplier():
    events, seen = run_chat(
        "Calder rang, kitchens now 30/06/2027",
        extraction("delivery_change", [item("PO-24170", "Kitchens", date(2027, 6, 30))]),
    )
    (change,) = [e for e in events if e.type == DELIVERY_DATE_CHANGED]
    assert seen["known"] == ["PO-24110", "PO-24170"]  # every order, not one sender's
    assert change.payload["po_number"] == "PO-24170"
    assert change.payload["new_delivery"] == "2027-06-30"
    assert change.payload["matched_by"] == "llm"  # PO wasn't typed, the LLM picked it


def test_chat_cannot_create_orders():
    events, _ = run_chat(
        "We ordered PO-30000 bricks for 01/03/2027",
        extraction("order_confirmation", [item("PO-30000", "Bricks", date(2027, 3, 1))]),
    )
    (review,) = [e for e in events if e.type == NEEDS_REVIEW]
    assert "New orders must come from the supplier's email, not chat" in review.payload["problems"]
