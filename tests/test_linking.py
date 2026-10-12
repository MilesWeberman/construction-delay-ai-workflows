from datetime import date

import pytest

from delay_ai.cpm import compute_schedule
from delay_ai.events import LINK_SUGGESTED, MATERIAL_LINKED, MATERIAL_ORDERED, Emit, EventStore
from delay_ai.linking import LinkSuggestion, make_link_handler, planner_link, suggest_by_rules
from delay_ai.loaders import load_schedule
from delay_ai.materials import build_materials, pending_link_suggestions
from delay_ai.models import Material


def material(description, po="PO-1"):
    return Material(
        po_number=po,
        description=description,
        supplier="s",
        supplier_email="orders@s.example",
        planned_delivery=date(2026, 12, 29),
    )


@pytest.fixture
def activities(sample_dir):
    return load_schedule(sample_dir / "schedule.csv")


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Structural steel frame (columns and beams)", "A05"),
        ("Precast concrete piles 300x300", "A02"),  # piles ~ piling
        ("13-person passenger lifts", "A14"),
        ("LVT floor finishes", None),  # floor slabs vs flooring: a tie
        ("Kitchen sets for the apartments", None),  # no shared words
    ],
)
def test_rules(activities, description, expected):
    assert suggest_by_rules(material(description), activities) == expected


def run_handler(activities, description, llm_activity_id):
    schedule = compute_schedule(activities, date(2026, 11, 2))

    def fake_llm(material, activities, schedule):
        return LinkSuggestion(activity_id=llm_activity_id, confidence=0.9, rationale="why")

    handler = make_link_handler(activities, schedule, fake_llm)
    store = EventStore()
    event = store.append(
        MATERIAL_ORDERED, {"material": material(description).model_dump(mode="json")}
    )
    return handler(event)


def test_links_when_rules_and_llm_agree(activities):
    (emit,) = run_handler(activities, "Structural steel frame", "A05")
    assert emit.type == MATERIAL_LINKED
    assert emit.payload["activity_id"] == "A05"
    assert emit.payload["linked_by"] == "rules_and_llm_agree"


def test_asks_planner_when_they_disagree(activities):
    (emit,) = run_handler(activities, "Plasterboard and metal studs", "A13")
    assert emit.type == LINK_SUGGESTED
    assert emit.payload["by_rules"] == "A06"  # "metal" decking: the rules are wrong here
    assert emit.payload["by_llm"] == "A13"


def test_ignores_activity_the_llm_made_up(activities):
    (emit,) = run_handler(activities, "Structural steel frame", "A99")
    assert emit.type == LINK_SUGGESTED
    assert emit.payload["by_llm"] is None


def test_planner_link_updates_materials_and_clears_suggestion():
    store = EventStore()
    store.append(MATERIAL_ORDERED, {"material": material("Plasterboard").model_dump(mode="json")})
    store.append(LINK_SUGGESTED, {"po_number": "PO-1", "by_rules": None, "by_llm": "A13"})
    assert len(pending_link_suggestions(store.all())) == 1

    emit: Emit = planner_link("PO-1", "A13")
    store.append(emit.type, emit.payload)

    (linked,) = build_materials(store.all())
    assert linked.activity_id == "A13"
    assert pending_link_suggestions(store.all()) == []
