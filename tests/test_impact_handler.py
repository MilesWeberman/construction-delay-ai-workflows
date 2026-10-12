from datetime import date

import pytest
from fakes import TRUE_LINKS, base_handlers

from delay_ai.cpm import compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    DELAY_ASSESSED,
    DELIVERY_DATE_CHANGED,
    MATERIAL_LINKED,
    MATERIAL_ORDERED,
    EventStore,
)
from delay_ai.impact import make_impact_handler
from delay_ai.linking import LinkSuggestion, make_link_handler, planner_link
from delay_ai.loaders import load_schedule
from delay_ai.orchestrator import Orchestrator, ingest_emails

START = date(2026, 11, 2)


@pytest.fixture
def activities(sample_dir):
    return load_schedule(sample_dir / "schedule.csv")


def orchestrator(store, activities, link=None):
    schedule = compute_schedule(activities, START)
    impact = make_impact_handler(store, activities, START)
    handlers = base_handlers(store, activities, schedule)
    if link:
        handlers[MATERIAL_ORDERED] = make_link_handler(activities, schedule, link)
    handlers[DELIVERY_DATE_CHANGED] = impact
    handlers[MATERIAL_LINKED] = impact
    return Orchestrator(store, handlers)


def assessments(store):
    return {e.payload["po_number"]: e.payload for e in store.all() if e.type == DELAY_ASSESSED}


def test_sample_inbox_assesses_every_delay(sample_dir, activities):
    store = EventStore()
    ingest_emails(FolderEmailSource(sample_dir / "emails"), store)
    orchestrator(store, activities).run()

    result = assessments(store)
    assert result["PO-24110"]["project_slip_days"] == 7  # steel
    assert result["PO-24110"]["new_finish"] == "2027-09-01"
    assert result["PO-24160"]["project_slip_days"] == 0  # lifts, absorbed by float
    # Kitchens alone would cost 3 days, but the steel delay (earlier the same day)
    # already pushed fit-out back 7 days, so the kitchen delay is now absorbed.
    assert result["PO-24170"]["project_slip_days"] == 0
    assert result["PO-24170"]["activity_slip_days"] == 0


def test_change_before_link_is_assessed_once_planner_links(sample_dir, activities):
    def no_kitchen_link(material, activities, schedule):
        activity = None if material.po_number == "PO-24170" else TRUE_LINKS[material.po_number]
        return LinkSuggestion(activity_id=activity, confidence=0.9, rationale="fake")

    store = EventStore()
    ingest_emails(FolderEmailSource(sample_dir / "emails"), store)
    run = orchestrator(store, activities, link=no_kitchen_link)
    run.run()
    assert "PO-24170" not in assessments(store)

    emit = planner_link("PO-24170", "A16")
    store.append(emit.type, emit.payload)
    run.run()
    assert assessments(store)["PO-24170"]["project_slip_days"] == 0  # behind steel, see above

    run.run()  # nothing new to assess
    assert len([e for e in store.all() if e.type == DELAY_ASSESSED]) == 3
