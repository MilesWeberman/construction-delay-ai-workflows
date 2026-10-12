from datetime import date

import pytest
from fakes import base_handlers
from test_planner import fake_propose

from delay_ai.actions import Draft, choose_option, make_action_handler
from delay_ai.cpm import compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    ACTION_PLAN_DRAFTED,
    DELAY_ASSESSED,
    DELIVERY_DATE_CHANGED,
    MATERIAL_LINKED,
    OPTION_CHOSEN,
    RECOVERY_OPTIONS_PROPOSED,
    EventStore,
)
from delay_ai.impact import make_impact_handler
from delay_ai.loaders import load_contacts, load_schedule
from delay_ai.orchestrator import Orchestrator, ingest_emails
from delay_ai.plan import current_activities
from delay_ai.planner import make_planner_handler

START = date(2026, 11, 2)


def fake_draft(project, option, contact, facts):
    return Draft(subject=f"{project}: {option.title}", body=f"Dear {contact.name},")


@pytest.fixture
def workflow(sample_dir):
    activities = load_schedule(sample_dir / "schedule.csv")
    contacts = load_contacts(sample_dir / "contacts.csv")
    store = EventStore()
    ingest_emails(FolderEmailSource(sample_dir / "emails"), store)
    impact = make_impact_handler(store, activities, START)
    handlers = base_handlers(store, activities, compute_schedule(activities, START)) | {
        DELIVERY_DATE_CHANGED: impact,
        MATERIAL_LINKED: impact,
        DELAY_ASSESSED: make_planner_handler(store, activities, START, fake_propose),
        OPTION_CHOSEN: make_action_handler(
            store, activities, START, contacts, "Riverside Court", fake_draft
        ),
    }
    orchestrator = Orchestrator(store, handlers)
    orchestrator.run()
    return store, orchestrator, activities


def choose(store, orchestrator, title):
    (proposal,) = [e for e in store.all() if e.type == RECOVERY_OPTIONS_PROPOSED]
    number = [o["title"] for o in proposal.payload["options"]].index(title) + 1
    emit = choose_option(proposal, number)
    store.append(emit.type, emit.payload)
    orchestrator.run()
    (plan,) = [e for e in store.all() if e.type == ACTION_PLAN_DRAFTED]
    return {m["to"]: m for m in plan.payload["messages"]}


def test_choosing_overtime_updates_plan_and_notifies_affected_people(workflow):
    store, orchestrator, activities = workflow
    messages = choose(store, orchestrator, "Overtime on decking")

    plan = {a.id: a for a in current_activities(activities, store.all())}
    assert plan["A06"].duration_days == 20

    # the project team, the steel foreman (A06) and trades whose work moves earlier
    assert "s.okafor@contractor.example" in messages
    assert "d.mitchell@pennine-steel.example" in messages
    assert "l.walsh@kirkstall-interiors.example" in messages
    assert "orders@pennine-steel.example" not in messages  # no supplier ask in this option

    steel = messages["d.mitchell@pennine-steel.example"]
    assert steel["body"].startswith("Dear Dave Mitchell,")
    assert "A06 to be done 5 working days faster" in steel["body"]
    pm = messages["s.okafor@contractor.example"]["body"]
    assert "Expected finish: 2027-08-26 (was 2027-09-01, 4 working days recovered)" in pm


def test_choosing_phased_delivery_asks_supplier_and_leaves_plan_alone(workflow):
    store, orchestrator, activities = workflow
    messages = choose(store, orchestrator, "Phased steel delivery")

    assert current_activities(activities, store.all()) == activities  # waits for supplier
    ask = messages["orders@pennine-steel.example"]["body"]
    assert "Can PO-24110 (Structural steel frame) be delivered on 2027-01-05" in ask
    assert "d.mitchell@pennine-steel.example" not in messages  # nothing moves yet
    pm = messages["s.okafor@contractor.example"]["body"]
    assert "4 working days recovered), if the supplier confirms the earlier delivery" in pm


def test_finish_is_recalculated_when_chosen_not_taken_from_the_proposal(workflow):
    # Seen in the first real run: options scored before kitchens were linked
    # claimed 9 days, but only 4 were left by the time one was chosen.
    store, orchestrator, _ = workflow
    (proposal,) = [e for e in store.all() if e.type == RECOVERY_OPTIONS_PROPOSED]
    emit = choose_option(proposal, 1)
    emit.payload["option"] |= {"recovered_days": 9, "new_finish": "2027-08-19"}  # stale
    store.append(emit.type, emit.payload)
    orchestrator.run()

    (plan,) = [e for e in store.all() if e.type == ACTION_PLAN_DRAFTED]
    pm = next(m for m in plan.payload["messages"] if m["role"] == "Project Manager")
    assert "Expected finish: 2027-08-26 (was 2027-09-01, 4 working days recovered)" in pm["body"]
    assert "2027-08-19" not in pm["body"]


def test_llm_only_sees_changes_without_dates(sample_dir):
    import re

    seen = []

    def spy_draft(project, option, contact, changes):
        seen.extend(changes)
        return Draft(subject="s", body="b")

    activities = load_schedule(sample_dir / "schedule.csv")
    store = EventStore()
    ingest_emails(FolderEmailSource(sample_dir / "emails"), store)
    impact = make_impact_handler(store, activities, START)
    handlers = base_handlers(store, activities, compute_schedule(activities, START)) | {
        DELIVERY_DATE_CHANGED: impact,
        MATERIAL_LINKED: impact,
        DELAY_ASSESSED: make_planner_handler(store, activities, START, fake_propose),
        OPTION_CHOSEN: make_action_handler(
            store, activities, START, load_contacts(sample_dir / "contacts.csv"), "P", spy_draft
        ),
    }
    orchestrator = Orchestrator(store, handlers)
    orchestrator.run()
    choose(store, orchestrator, "Overtime on decking")

    assert "A06 to be done faster" in seen
    assert "A07 Roof structure: starts earlier" in seen
    assert not [c for c in seen if re.search(r"\d{4}-\d{2}-\d{2}|\d+ working days", c)]
