from datetime import date

import pytest
from fakes import base_handlers
from test_planner import edit, option

from delay_ai.chat import Answer, Intent, make_chat_handler
from delay_ai.cpm import compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    CHAT_MESSAGE_RECEIVED,
    CHAT_REPLIED,
    DELIVERY_DATE_CHANGED,
    EMAIL_RECEIVED,
    MATERIAL_LINKED,
    RECOVERY_OPTIONS_PROPOSED,
    EventStore,
)
from delay_ai.extraction import EmailExtraction, ExtractedItem
from delay_ai.impact import make_impact_handler
from delay_ai.ingestion import make_email_handler
from delay_ai.loaders import load_schedule
from delay_ai.orchestrator import Orchestrator, ingest_chat, ingest_emails
from delay_ai.planner import RecoveryPlan

START = date(2026, 11, 2)


@pytest.fixture
def setup(sample_dir):
    activities = load_schedule(sample_dir / "schedule.csv")
    store = EventStore()
    ingest_emails(FolderEmailSource(sample_dir / "emails"), store)
    handlers = base_handlers(store, activities, compute_schedule(activities, START))
    impact = make_impact_handler(store, activities, START)
    handlers |= {DELIVERY_DATE_CHANGED: impact, MATERIAL_LINKED: impact}
    Orchestrator(store, handlers).run()
    return store, activities, handlers


def send(setup, text, intent, **fakes):
    store, activities, handlers = setup
    messages = handlers[EMAIL_RECEIVED]
    chat = make_chat_handler(
        store, activities, START, messages, classify=lambda t: Intent(intent=intent), **fakes
    )
    message = ingest_chat(text, "Priya", store)
    Orchestrator(store, handlers | {CHAT_MESSAGE_RECEIVED: chat}).run()
    new = [e for e in store.all() if e.id > message.id]
    (reply,) = [e for e in new if e.type == CHAT_REPLIED]
    return new, reply.payload["text"]


def test_suggested_change_is_scored_and_can_be_chosen(setup):
    plan = RecoveryPlan(
        options=[
            option(
                "Glazing follows decking",
                edit("remove_dependency", activity_id="A09", predecessor_id="A06"),
            )
        ]
    )
    new, text = send(setup, "Start glazing during decking", "schedule_change",
                     propose_change=lambda t, p: plan)  # fmt: skip

    (proposal,) = [e for e in new if e.type == RECOVERY_OPTIONS_PROPOSED]
    (scored,) = proposal.payload["options"]
    assert proposal.payload["po_number"] is None
    assert scored["recovered_days"] > 0
    assert text.startswith("I've modelled it: **Glazing follows decking** wins back")


def test_impossible_change_is_explained(setup):
    plan = RecoveryPlan(
        options=[option("Halve steel", edit("shorten", activity_id="A05", days=10))]
    )
    new, text = send(
        setup, "Halve steel erection", "schedule_change", propose_change=lambda t, p: plan
    )
    assert text == "I couldn't model that (Cannot shorten A05 by 10 (max 6))."
    assert not [e for e in new if e.type == RECOVERY_OPTIONS_PROPOSED]  # no empty card


def test_question_is_answered_with_the_live_plan(setup):
    seen = {}

    def answer(text, plan):
        seen["plan"] = plan
        return Answer(text="Because steel already pushed fit-out back.")

    _, text = send(setup, "Why are kitchens not critical?", "question", answer=answer)
    assert text == "Because steel already pushed fit-out back."
    assert "Current finish: 2027-09-01" in seen["plan"]


def test_delivery_news_uses_the_email_pipeline(setup):
    store, activities, handlers = setup
    news = EmailExtraction(
        kind="delivery_change",
        supplier=None,
        items=[
            ExtractedItem(
                po_number="PO-24130",
                description="Curtain wall",
                quantity=None,
                unit=None,
                delivery_date=date(2027, 3, 10),
            )
        ],
        reason="phone call",
        confidence=0.9,
    )
    chat_extract = make_email_handler(store, lambda message, facts, known: news)
    text = "Clearview rang: curtain wall PO-24130 now 10/03/2027"

    with_news = (store, activities, handlers | {EMAIL_RECEIVED: chat_extract})
    new, reply = send(with_news, text, "delivery_news")
    assert any(e.type == DELIVERY_DATE_CHANGED for e in new)
    assert (
        reply == "Thanks, noted. Unitised curtain wall panels: delivery moved from 3 Mar to 10 Mar."
    )
