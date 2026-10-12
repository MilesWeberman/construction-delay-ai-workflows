"""Link each material to the activity that needs it.

Rules and the LLM each suggest an activity. When they agree the link is made;
otherwise a planner confirms it.
"""

import re
from collections.abc import Callable

from pydantic import BaseModel, Field

from delay_ai.cpm import Schedule
from delay_ai.events import LINK_SUGGESTED, MATERIAL_LINKED, Emit, Event
from delay_ai.llm import complete_structured
from delay_ai.models import Activity, Material

STOPWORDS = {"and", "for", "the", "with", "upper", "all"}


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {_stem(w) for w in words if len(w) > 2 and w not in STOPWORDS}


def suggest_by_rules(material: Material, activities: list[Activity]) -> str | None:
    """The activity whose name shares the most words with the material, if one stands out."""
    material_words = _words(material.description)
    scores = {a.id: len(material_words & _words(a.name)) for a in activities}
    best = max(scores.values(), default=0)
    winners = [activity_id for activity_id, score in scores.items() if score == best]
    return winners[0] if best > 0 and len(winners) == 1 else None


class LinkSuggestion(BaseModel):
    activity_id: str | None = Field(description="ID of the activity that needs this material")
    confidence: float = Field(description="0 to 1")
    rationale: str = Field(description="One sentence")


SYSTEM_PROMPT = """You are an experienced UK construction planner.
Given a material order and the programme, pick the one activity that cannot start
until this material is on site. Use your knowledge of how buildings are built
(e.g. rebar is needed for pile caps, plasterboard for drylining). The planned
delivery is usually shortly before the activity starts. If no activity fits,
return null."""


def suggest_with_llm(
    material: Material, activities: list[Activity], schedule: Schedule
) -> LinkSuggestion:
    programme = "\n".join(
        f"- {a.id}: {a.name} ({a.trade}), starts {schedule.start_of(a.id)}" for a in activities
    )
    user = f"""Material: {material.description}
Supplier: {material.supplier}
Planned delivery: {material.planned_delivery}

Programme:
{programme}"""
    return complete_structured(SYSTEM_PROMPT, user, LinkSuggestion)


LlmSuggester = Callable[[Material, list[Activity], Schedule], LinkSuggestion]


def make_link_handler(
    activities: list[Activity], schedule: Schedule, suggest: LlmSuggester
) -> Callable[[Event], list[Emit]]:
    activity_ids = {a.id for a in activities}

    def handle(event: Event) -> list[Emit]:
        material = Material.model_validate(event.payload["material"])
        by_rules = suggest_by_rules(material, activities)
        llm = suggest(material, activities, schedule)
        by_llm = llm.activity_id if llm.activity_id in activity_ids else None

        if by_rules and by_rules == by_llm:
            return [
                Emit(
                    MATERIAL_LINKED,
                    {
                        "po_number": material.po_number,
                        "activity_id": by_rules,
                        "linked_by": "rules_and_llm_agree",
                        "rationale": llm.rationale,
                    },
                )
            ]
        return [
            Emit(
                LINK_SUGGESTED,
                {
                    "po_number": material.po_number,
                    "by_rules": by_rules,
                    "by_llm": by_llm,
                    "llm_confidence": llm.confidence,
                    "rationale": llm.rationale,
                },
            )
        ]

    return handle


def planner_link(po_number: str, activity_id: str) -> Emit:
    return Emit(
        MATERIAL_LINKED,
        {"po_number": po_number, "activity_id": activity_id, "linked_by": "planner"},
    )
