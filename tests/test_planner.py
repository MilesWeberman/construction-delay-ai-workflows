from datetime import date

import pytest
from fakes import base_handlers

from delay_ai.cpm import compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    DELAY_ASSESSED,
    DELIVERY_DATE_CHANGED,
    MATERIAL_LINKED,
    RECOVERY_OPTIONS_PROPOSED,
    EventStore,
)
from delay_ai.impact import make_impact_handler
from delay_ai.loaders import load_schedule
from delay_ai.models import Material
from delay_ai.orchestrator import Orchestrator, ingest_emails
from delay_ai.plan import Edit, apply_edits
from delay_ai.planner import RecoveryOption, RecoveryPlan, make_planner_handler

START = date(2026, 11, 2)
TODAY = date(2026, 10, 12)


def edit(type, **fields):
    defaults = dict(
        activity_id=None, predecessor_id=None, days=None, po_number=None, new_delivery=None
    )
    return Edit(type=type, **{**defaults, **fields})


def option(title, *edits):
    return RecoveryOption(title=title, edits=list(edits), rationale="r", risks="r", cost="c")


@pytest.fixture
def activities(sample_dir):
    return load_schedule(sample_dir / "schedule.csv")


STEEL = Material(
    po_number="PO-24110",
    description="Steel",
    supplier="Pennine",
    supplier_email="orders@pennine-steel.example",
    planned_delivery=date(2027, 1, 12),
    activity_id="A05",
)


def test_apply_edits(activities):
    edits = [
        edit("shorten", activity_id="A06", days=5),
        edit("remove_dependency", activity_id="A10", predecessor_id="A06"),
        edit("change_delivery", po_number="PO-24110", new_delivery=date(2027, 1, 5)),
    ]
    acts, mats, problems = apply_edits(edits, activities, [STEEL], TODAY)
    by_id = {a.id: a for a in acts}

    assert problems == []
    assert by_id["A06"].duration_days == 20
    assert by_id["A10"].predecessors == []
    assert mats[0].planned_delivery == date(2027, 1, 5)
    # the originals are untouched
    assert {a.id: a for a in activities}["A06"].duration_days == 25


@pytest.mark.parametrize(
    "bad_edit",
    [
        edit("shorten", activity_id="A06", days=10),  # more than 30% of 25 days
        edit("shorten", activity_id="A11", days=1),  # a milestone
        edit("remove_dependency", activity_id="A12", predecessor_id="A05"),  # not a link
        edit("change_delivery", po_number="PO-24110", new_delivery=date(2027, 2, 1)),  # later
        edit("change_delivery", po_number="PO-24110", new_delivery=date(2026, 10, 1)),  # past
        edit("shorten", activity_id="A99", days=1),
    ],
)
def test_invalid_edits_are_reported(activities, bad_edit):
    _, _, problems = apply_edits([bad_edit], activities, [STEEL], TODAY)
    assert len(problems) == 1


def fake_propose(impact, schedule, activities, materials):
    return RecoveryPlan(
        options=[
            option("Overtime on decking", edit("shorten", activity_id="A06", days=5)),
            option(
                "Phased steel delivery",
                edit("change_delivery", po_number="PO-24110", new_delivery=date(2027, 1, 5)),
            ),
            option("Impossible", edit("shorten", activity_id="A05", days=15)),
        ]
    )


def test_steel_delay_gets_scored_options(sample_dir, activities, monkeypatch):
    store = EventStore()
    ingest_emails(FolderEmailSource(sample_dir / "emails"), store)
    handlers = base_handlers(store, activities, compute_schedule(activities, START))
    impact = make_impact_handler(store, activities, START)
    handlers |= {
        DELIVERY_DATE_CHANGED: impact,
        MATERIAL_LINKED: impact,
        DELAY_ASSESSED: make_planner_handler(store, activities, START, fake_propose),
    }
    Orchestrator(store, handlers).run()

    proposals = [e for e in store.all() if e.type == RECOVERY_OPTIONS_PROPOSED]
    (steel,) = proposals  # lifts and kitchens are absorbed, so only steel gets options
    options = steel.payload["options"]

    # Each edit wins back 5 days on steel, but then the late kitchens (23 June)
    # become the constraint again, so only 4 days are really recovered.
    recovered = {o["title"]: o["recovered_days"] for o in options}
    assert recovered == {"Overtime on decking": 4, "Phased steel delivery": 4}
    assert options[0]["new_finish"] == "2027-08-26"  # 7 days late, 4 recovered
    assert steel.payload["rejected"][0]["title"] == "Impossible"


def test_no_options_when_delay_is_absorbed(activities):
    store = EventStore()
    called = []
    handler = make_planner_handler(store, activities, START, lambda *a: called.append(a))
    event = store.append(DELAY_ASSESSED, {
        "po_number": "PO-24160", "activity_id": "A14", "old_delivery": "2027-03-03",
        "new_delivery": "2027-03-24", "float_before_days": 85, "activity_slip_days": 13,
        "project_slip_days": 0, "old_finish": "2027-08-23", "new_finish": "2027-08-23",
        "delayed_activities": ["A14"], "change_event": 1,
    })  # fmt: skip
    assert handler(event) == []
    assert called == []


def test_planner_prompt_includes_all_knowledge_files():
    from delay_ai.planner import SYSTEM_PROMPT

    assert "# Construction context (UK)" in SYSTEM_PROMPT
    assert "# Scheduling context" in SYSTEM_PROMPT
    assert "# Planning playbook" in SYSTEM_PROMPT
