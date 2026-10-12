"""The chat box: delivery news, suggested schedule changes, and questions.

The LLM decides which of the three a message is. News goes through the same
pipeline as email. A suggested change becomes schedule edits that the CPM
scores, and can then be chosen like a recovery option. Questions are answered
from the knowledge files and the live plan.
"""

from collections.abc import Callable
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from delay_ai import knowledge
from delay_ai.events import (
    CHAT_REPLIED,
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    NEEDS_REVIEW,
    RECOVERY_OPTIONS_PROPOSED,
    Emit,
    Event,
    EventStore,
)
from delay_ai.impact import schedule_with_materials
from delay_ai.llm import complete_structured
from delay_ai.materials import build_materials
from delay_ai.models import Activity
from delay_ai.plan import current_activities
from delay_ai.planner import RecoveryPlan, describe_plan, evaluate_options


class Intent(BaseModel):
    intent: Literal["delivery_news", "schedule_change", "question"] = Field(
        description="""delivery_news: news about a material order or delivery date.
schedule_change: the user proposes changing the programme (resequence, speed up,
ask a supplier for an earlier delivery).
question: anything else, e.g. asking about the plan, a delay or construction."""
    )


class Answer(BaseModel):
    text: str


def classify_with_llm(text: str) -> Intent:
    return complete_structured(
        "Classify a message typed into a construction scheduling assistant.", text, Intent
    )


CHANGE_PROMPT = f"""You are a senior UK construction planner. The user suggests a
change to the programme. Turn it into one option made of edits:
- remove_dependency: let activity_id start without waiting for predecessor_id
- shorten: take days off activity_id (extra labour, longer shifts)
- change_delivery: ask the supplier of po_number to deliver earlier, on new_delivery
Model what the user asked for, even if you have doubts; put doubts in the risks.
Days recovered are calculated afterwards, so don't state them.

{knowledge.load()}"""


def propose_change_with_llm(text: str, plan: str) -> RecoveryPlan:
    return complete_structured(CHANGE_PROMPT, f"Suggestion: {text}\n\n{plan}", RecoveryPlan)


ANSWER_PROMPT = f"""You are a senior UK construction planner answering questions
about a live project programme. Be concise and practical. Only quote dates and
numbers that appear in the programme you are given; never calculate new ones.

{knowledge.load()}"""


def answer_with_llm(text: str, plan: str) -> Answer:
    return complete_structured(ANSWER_PROMPT, f"Question: {text}\n\n{plan}", Answer)


def make_chat_handler(
    store: EventStore,
    base: list[Activity],
    start_date: date,
    message_handler: Callable[[Event], list[Emit]],
    classify: Callable[[str], Intent] = classify_with_llm,
    propose_change: Callable[[str, str], RecoveryPlan] = propose_change_with_llm,
    answer: Callable[[str, str], Answer] = answer_with_llm,
) -> Callable[[Event], list[Emit]]:
    def reply(event: Event, text: str) -> Emit:
        return Emit(CHAT_REPLIED, {"chat_event": event.id, "text": text})

    def handle(event: Event) -> list[Emit]:
        text = event.payload["body"]
        intent = classify(text).intent
        if intent == "delivery_news":
            emits = message_handler(event)
            return [*emits, reply(event, summarise_news(emits))]

        events = store.all()
        materials = build_materials(events)
        activities = current_activities(base, events)
        schedule = schedule_with_materials(activities, materials, start_date)
        plan = describe_plan(schedule, activities, materials)
        plan += f"\n\nCurrent finish: {schedule.finish_date}"

        if intent == "question":
            return [reply(event, answer(text, plan).text)]

        proposed = propose_change(text, plan).options
        options, rejected = evaluate_options(
            proposed, activities, materials, start_date, event.created_at.date()
        )
        payload = {
            "chat_event": event.id,
            "po_number": None,
            "options": [o.model_dump(mode="json") for o in options],
            "rejected": rejected,
        }
        if options:
            best = options[0]
            effect = (
                f"recovers {best.recovered_days} working days (finish {best.new_finish})"
                if best.recovered_days > 0
                else f"doesn't bring the finish forward (finish {best.new_finish})"
            )
            text = f"I modelled '{best.title}': it {effect}. Choose it to update the plan."
        else:
            reasons = "; ".join(p for r in rejected for p in r["problems"])
            text = f"I couldn't model that change: {reasons or 'no edits found'}."
        return [Emit(RECOVERY_OPTIONS_PROPOSED, payload), reply(event, text)]

    return handle


def summarise_news(emits: list[Emit]) -> str:
    lines = []
    for e in emits:
        p = e.payload
        if e.type == DELIVERY_DATE_CHANGED:
            lines.append(
                f"Recorded: {p['po_number']} moves {p['old_delivery']} -> {p['new_delivery']}."
            )
        elif e.type == DELIVERY_CONFIRMED:
            lines.append(f"Recorded: {p['po_number']} confirmed as planned.")
        elif e.type == NEEDS_REVIEW:
            lines.append("Sent for review: " + "; ".join(p["problems"]))
    return " ".join(lines) or "Noted, but there was nothing to record."
