"""Wires every handler to its event type. Shared by the CLI and the app."""

from pathlib import Path

from delay_ai.actions import draft_with_llm, make_action_handler
from delay_ai.chat import make_chat_handler
from delay_ai.cpm import compute_schedule
from delay_ai.events import (
    CHAT_MESSAGE_RECEIVED,
    DELAY_ASSESSED,
    DELIVERY_DATE_CHANGED,
    EMAIL_RECEIVED,
    MATERIAL_LINKED,
    MATERIAL_ORDERED,
    OPTION_CHOSEN,
    EventStore,
)
from delay_ai.extraction import extract_with_llm
from delay_ai.impact import make_impact_handler
from delay_ai.ingestion import make_email_handler
from delay_ai.linking import make_link_handler, suggest_with_llm
from delay_ai.loaders import load_contacts, load_project, load_schedule
from delay_ai.orchestrator import Handler
from delay_ai.planner import make_planner_handler, propose_with_llm


def handlers(store: EventStore, data: Path) -> dict[str, Handler]:
    activities = load_schedule(data / "schedule.csv")
    project = load_project(data / "project.json")
    start_date = project.start_date
    contacts = load_contacts(data / "contacts.csv")
    schedule = compute_schedule(activities, start_date)
    impact = make_impact_handler(store, activities, start_date)
    messages = make_email_handler(store, extract_with_llm)
    return {
        EMAIL_RECEIVED: messages,
        CHAT_MESSAGE_RECEIVED: make_chat_handler(store, activities, start_date, messages),
        MATERIAL_ORDERED: make_link_handler(activities, schedule, suggest_with_llm),
        DELIVERY_DATE_CHANGED: impact,
        MATERIAL_LINKED: impact,
        DELAY_ASSESSED: make_planner_handler(store, activities, start_date, propose_with_llm),
        OPTION_CHOSEN: make_action_handler(
            store, activities, start_date, contacts, project.name, draft_with_llm
        ),
    }
