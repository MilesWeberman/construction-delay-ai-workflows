"""The chat box: delivery news, site news, suggested schedule changes, and questions.

The LLM decides which of the four a message is. Delivery news goes through the
same pipeline as email. Site news (weather, labour, plant, access) becomes "takes
longer" or "can't start before" edits that are applied to the plan. A suggested
change becomes edits that the CPM scores, and can then be chosen like a recovery
option. Questions are answered from the knowledge files and the live plan.
"""

from collections.abc import Callable
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from delay_ai import knowledge
from delay_ai.events import (
    ACTIVITY_DISRUPTED,
    CHAT_MESSAGE_RECEIVED,
    CHAT_REPLIED,
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    NEEDS_REVIEW,
    OPTION_CHOSEN,
    RECOVERY_OPTIONS_PROPOSED,
    Emit,
    Event,
    EventStore,
)
from delay_ai.impact import schedule_with_materials
from delay_ai.ingestion import MIN_CONFIDENCE
from delay_ai.llm import complete_structured
from delay_ai.materials import build_materials
from delay_ai.models import Activity, Material
from delay_ai.plan import SITE_EDITS, Edit, apply_edits, current_activities
from delay_ai.planner import RecoveryPlan, describe_plan, evaluate_options


class Intent(BaseModel):
    intent: Literal["delivery_news", "site_news", "schedule_change", "question"] = Field(
        description="""delivery_news: news about a material order or delivery date.
site_news: something on site stops or slows work: weather, labour or crew
availability, plant breakdown, access, a failed inspection.
schedule_change: the user proposes or asks about changing the programme, including
questions like "Can curtain walling follow the frame floor by floor?" or "What if we add a second
gang?" (resequence, speed up, ask a supplier for an earlier delivery).
question: anything else, e.g. why something is late, when a task starts, what a
delay means."""
    )


class SiteNews(BaseModel):
    edits: list[Edit] = Field(
        description="Only lengthen (a task takes extra working days) or not_before "
        "(a task can't start before a date). Empty if no task is affected."
    )
    explanation: str = Field(
        description="One short, friendly sentence on what this means for the schedule. "
        "If no task is affected, say why, e.g. 'No crane lifts are planned between 15 "
        "and 19 Oct, as the steel starts in January, so the schedule isn't affected.'"
    )
    reason: str = Field(description="A few words, e.g. 'storm, no crane lifts'")
    confidence: float = Field(description="0 to 1")


class Answer(BaseModel):
    text: str


def classify_with_llm(text: str) -> Intent:
    return complete_structured(
        "Classify a message typed into a construction scheduling assistant.", text, Intent
    )


CHANGE_PROMPT = f"""You are a senior UK construction planner. The user suggests a
change to the programme. Turn it into one option made of edits:
- remove_dependency: let activity_id start without waiting for predecessor_id
- add_dependency: make activity_id wait for predecessor_id (to change the order)
- shorten: take days off activity_id (extra labour, longer shifts)
- change_delivery: ask the supplier of po_number to deliver earlier, on new_delivery
Use only these four edit types, never lengthen or not_before.
Model exactly what the user describes, not a different idea you prefer:
- more people, a second gang or crew, longer shifts, weekend working → shorten
  that activity (be realistic: a second gang rarely halves a task)
- starting work earlier or overlapping it ("floor by floor", "while X is still
  going") → remove_dependency from the predecessor it would otherwise wait for
- doing one task before another → add_dependency (with remove_dependency to swap)
- asking a supplier for an earlier date → change_delivery
Put any doubts in the risks.
Days recovered are calculated afterwards, so don't state them.

{knowledge.load()}"""


def propose_change_with_llm(text: str, plan: str) -> RecoveryPlan:
    return complete_structured(CHANGE_PROMPT, f"Suggestion: {text}\n\n{plan}", RecoveryPlan)


SITE_PROMPT = f"""You are a senior UK construction planner. A member of the site
team reports something that stops or slows work. Turn it into edits to the
programme:
- lengthen: activity_id takes `days` more working days (e.g. a smaller gang, or
  days lost to weather while the task is under way)
- not_before: activity_id can't start before the date `not_before` (e.g. the crew
  isn't available until then, or a weather window)
Work out the affected tasks yourself: use the dates in the programme (each task
runs from its start to its end date) and your construction knowledge (e.g. crane
lifts are needed for steel erection, decking, roof structure and curtain walling;
rain stops roofing and external works). Only edit tasks under way or due to start
in the period the news covers. If no task is affected, return no edits and say
why in the explanation. Lower your confidence only if the news itself is unclear.

{knowledge.load()}"""


def extract_site_news_with_llm(text: str, plan: str, today: date) -> SiteNews:
    user = f"Today is {today:%A %d %B %Y}.\nSite news: {text}\n\n{plan}"
    return complete_structured(SITE_PROMPT, user, SiteNews)


ANSWER_PROMPT = f"""You are a senior UK construction planner chatting with the
project team about their live programme. Reply like a colleague in a chat:
friendly, plain and short (two to four sentences; no headings, and no lists
unless asked). Only quote dates and numbers that appear in the programme you are
given; never calculate new ones.

{knowledge.load()}"""


def answer_with_llm(text: str, plan: str) -> Answer:
    return complete_structured(ANSWER_PROMPT, f"Question: {text}\n\n{plan}", Answer)


def recent_conversation(events: list[Event], before: int, turns: int = 6) -> str:
    """The last few chat messages, so follow-ups like 'and the kitchens?' make sense."""
    replies = {e.payload["chat_event"]: e.payload["text"] for e in events if e.type == CHAT_REPLIED}
    lines = []
    for e in events:
        if e.type == CHAT_MESSAGE_RECEIVED and e.id < before:
            lines.append(f"User: {e.payload['body']}")
            if e.id in replies:
                lines.append(f"Assistant: {replies[e.id]}")
    return "\n".join(lines[-turns:])


def make_chat_handler(
    store: EventStore,
    base: list[Activity],
    start_date: date,
    message_handler: Callable[[Event], list[Emit]],
    classify: Callable[[str], Intent] = classify_with_llm,
    propose_change: Callable[[str, str], RecoveryPlan] = propose_change_with_llm,
    answer: Callable[[str, str], Answer] = answer_with_llm,
    extract_site_news: Callable[[str, str, date], SiteNews] = extract_site_news_with_llm,
) -> Callable[[Event], list[Emit]]:
    def reply(event: Event, text: str) -> Emit:
        return Emit(CHAT_REPLIED, {"chat_event": event.id, "text": text})

    def handle(event: Event) -> list[Emit]:
        text = event.payload["body"]
        events = store.all()
        history = recent_conversation(events, event.id)
        said = f"Recent conversation:\n{history}\n\nNew message: {text}" if history else text
        intent = classify(said).intent
        materials = build_materials(events)
        if intent == "delivery_news":
            emits = message_handler(event)
            return [*emits, reply(event, summarise_news(emits, materials))]

        activities = current_activities(base, events)
        names = {a.id: a.name for a in activities}
        schedule = schedule_with_materials(activities, materials, start_date)
        plan = describe_plan(schedule, activities, materials)
        plan += f"\n\nCurrent finish: {schedule.finish_date}"
        if changes := what_changed(events, materials):
            plan += f"\n\nWhat has changed so far:\n{changes}"
        if history:
            plan += f"\n\nRecent conversation:\n{history}"

        if intent == "question":
            return [reply(event, answer(text, plan).text)]

        if intent == "site_news":
            today = event.created_at.date()
            news = extract_site_news(text, plan, today)
            if not news.edits:
                return [reply(event, news.explanation or NOT_SURE)]
            changed, _, problems = apply_edits(news.edits, activities, materials, today)
            problems += [e.type for e in news.edits if e.type not in SITE_EDITS]
            if problems or news.confidence < MIN_CONFIDENCE:
                return [reply(event, NOT_SURE)]
            summary = "; ".join(describe_site_edit(e, names) for e in news.edits)
            payload = {
                "chat_event": event.id,
                "edits": [e.model_dump(mode="json") for e in news.edits],
                "reason": news.reason,
                "summary": f"{summary} ({news.reason})",
            }
            after = schedule_with_materials(changed, materials, start_date)
            slip = after.duration_days - schedule.duration_days
            done = "; ".join(say_site_edit(e, names) for e in news.edits)
            effect = (
                f"That pushes completion {plural(slip, 'working day')} later, to "
                f"{after.finish_date:%-d %b}. I've suggested ways to recover on the schedule."
                if slip > 0
                else "There's enough slack, so completion doesn't move."
            )
            return [Emit(ACTIVITY_DISRUPTED, payload), reply(event, f"Got it. {done}. {effect}")]

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
        if options and options[0].recovered_days > 0:
            best = options[0]
            text = (
                f"I've modelled it: **{best.title}** wins back "
                f"{plural(best.recovered_days, 'working day')} (completion "
                f"{best.new_finish:%-d %b}). Choose it on the schedule to apply it."
            )
        elif options:
            text = (
                f"I've modelled **{options[0].title}**, but it doesn't bring completion "
                "forward: something else is holding the finish."
            )
        else:
            reasons = "; ".join(p for r in rejected for p in r["problems"])
            text = (
                f"I couldn't model that ({reasons})."
                if reasons and "recover time" not in reasons
                else "I couldn't turn that into a change I can check. Could you put it another "
                "way, e.g. *add a second steel erection gang*?"
            )
        if not options:  # nothing to choose, so no card on the schedule; the reply says why
            return [reply(event, text)]
        return [Emit(RECOVERY_OPTIONS_PROPOSED, payload), reply(event, text)]

    return handle


def what_changed(events: list[Event], materials: list[Material]) -> str:
    """Delivery moves (with reasons), site news and chosen options, oldest first."""
    names = {m.po_number: m.description for m in materials}
    lines = []
    for e in events:
        p = e.payload
        if e.type == DELIVERY_DATE_CHANGED:
            reason = f" ({p['reason']})" if p.get("reason") else ""
            lines.append(
                f"- {names.get(p['po_number'], p['po_number'])} ({p['po_number']}) delivery "
                f"moved from {p['old_delivery']} to {p['new_delivery']}{reason}"
            )
        elif e.type == ACTIVITY_DISRUPTED:
            lines.append(f"- Site news: {p['summary']}")
        elif e.type == OPTION_CHOSEN:
            lines.append(f"- Recovery option chosen: {p['option']['title']}")
    return "\n".join(lines)


NOT_SURE = (
    "I'm not sure which work that affects. Could you say which task it hits and for "
    "how long? For example: *the steel erection loses two days*."
)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def describe_site_edit(edit: Edit, names: dict[str, str]) -> str:
    """For the alert: '<task> takes 3 more working days'."""
    name = names[edit.activity_id]
    if edit.type == "lengthen":
        return f"{name} takes {plural(edit.days, 'more working day')}"
    return f"{name} can't start before {edit.not_before:%d %b %Y}"


def say_site_edit(edit: Edit, names: dict[str, str]) -> str:
    """For the chat: 'I've added 3 working days to <task>'."""
    name = names[edit.activity_id]
    if edit.type == "lengthen":
        return f"I've added {plural(edit.days, 'working day')} to {name.lower()}"
    return f"{name} now can't start before {edit.not_before:%-d %b}"


def summarise_news(emits: list[Emit], materials: list[Material]) -> str:
    names = {m.po_number: m.description[:1].upper() + m.description[1:] for m in materials}
    lines = []
    for e in emits:
        p = e.payload
        what = names.get(p.get("po_number"), p.get("po_number"))
        if e.type == DELIVERY_DATE_CHANGED:
            old, new = date.fromisoformat(p["old_delivery"]), date.fromisoformat(p["new_delivery"])
            lines.append(
                f"Thanks, noted. {what}: delivery moved from {old:%-d %b} to {new:%-d %b}."
            )
        elif e.type == DELIVERY_CONFIRMED:
            lines.append(f"Thanks, noted. {what}: delivery confirmed as planned.")
        elif e.type == NEEDS_REVIEW:
            problems = "; ".join(p["problems"]).lower()
            lines.append(
                f"I couldn't record that ({problems}). Could you give the order and the new date?"
            )
    return " ".join(lines) or "Thanks. There was nothing to change on the schedule."
