"""Draft the messages that put a chosen option into action.

Code decides who hears what (recipients and dates); the LLM only writes the
wording, and the facts are appended to every message unchanged. Nothing is sent.
"""

from collections.abc import Callable
from datetime import date

from pydantic import BaseModel

from delay_ai.cpm import Schedule
from delay_ai.events import ACTION_PLAN_DRAFTED, OPTION_CHOSEN, Emit, Event, EventStore
from delay_ai.impact import schedule_with_materials
from delay_ai.llm import complete_structured
from delay_ai.materials import build_materials
from delay_ai.models import Activity, Contact, Material
from delay_ai.plan import apply_edits, current_activities
from delay_ai.planner import EvaluatedOption


class Draft(BaseModel):
    subject: str
    body: str


def recipients(
    option: EvaluatedOption,
    contacts: list[Contact],
    materials: list[Material],
    activities: list[Activity],
    before: Schedule,
    after: Schedule,
    expected: Schedule,
) -> list[tuple[Contact, list[str]]]:
    """Everyone affected by the option, with the facts that matter to each of them.

    after is the plan once the option is applied; expected also assumes any
    earlier deliveries asked for are confirmed.
    """
    names = {a.id: a.name for a in activities}
    edited = {e.activity_id for e in option.edits if e.activity_id}
    moved = {a.id for a in activities if before.start_of(a.id) != after.start_of(a.id)}

    def activity_facts(ids: set[str]) -> list[str]:
        facts = []
        for activity_id in sorted(ids & (edited | moved)):
            old, new = before.start_of(activity_id), after.start_of(activity_id)
            start = f"start {new}" if old == new else f"start moves {old} -> {new}"
            facts.append(f"{activity_id} {names[activity_id]}: {start}")
        for e in option.edits:
            if e.type == "shorten" and e.activity_id in ids:
                facts.append(f"{e.activity_id} to be done {e.days} working days faster")
            if e.type == "remove_dependency" and e.activity_id in ids:
                facts.append(f"{e.activity_id} no longer waits for {e.predecessor_id}")
        return facts

    result = []
    for contact in contacts:
        if not contact.activity_ids:  # project team: hears about everything
            recovered = before.duration_days - expected.duration_days
            finish = f"Expected finish: {expected.finish_date} (was {before.finish_date}, "
            finish += f"{recovered} working days recovered)"
            if any(e.type == "change_delivery" for e in option.edits):
                finish += ", if the supplier confirms the earlier delivery"
            facts = [f"Option chosen: {option.title}", finish, *activity_facts(set(names))]
            result.append((contact, facts))
        elif facts := activity_facts(set(contact.activity_ids)):
            result.append((contact, facts))

    by_po = {m.po_number: m for m in materials}
    for e in option.edits:
        if e.type == "change_delivery" and e.po_number in by_po:
            m = by_po[e.po_number]
            supplier = Contact(
                name=m.supplier, role="Supplier", company=m.supplier, email=m.supplier_email
            )
            ask = (
                f"Can {e.po_number} ({m.description}) be delivered on {e.new_delivery} "
                f"instead of {m.planned_delivery}?"
            )
            result.append((supplier, [ask]))
    return result


SYSTEM_PROMPT = """You write short, clear emails from a UK main contractor's project
team to colleagues, subcontractors and suppliers about a programme change.
Be direct and practical. Say what changes for the reader and what you need from
them. Never write dates, durations or day counts: the key facts are appended
below your text, and they are the only source of numbers. Don't mention earlier
conversations or agreements; this message is the first the reader hears of it.
Don't add a sign-off name; sign as "{project} project team"."""


def draft_with_llm(
    project: str, option: EvaluatedOption, contact: Contact, facts: list[str]
) -> Draft:
    user = f"""To: {contact.name}, {contact.role}, {contact.company}
Change: {option.title}
Why: {option.rationale}
Facts for this reader:
""" + "\n".join(f"- {f}" for f in facts)
    return complete_structured(SYSTEM_PROMPT.format(project=project), user, Draft)


Drafter = Callable[[str, EvaluatedOption, Contact, list[str]], Draft]


def make_action_handler(
    store: EventStore,
    base: list[Activity],
    start_date: date,
    contacts: list[Contact],
    project: str,
    draft: Drafter,
) -> Callable[[Event], list[Emit]]:
    def handle(event: Event) -> list[Emit]:
        events = store.all()
        option = EvaluatedOption.model_validate(event.payload["option"])
        materials = build_materials(events)
        before_acts = current_activities(base, [e for e in events if e.id < event.id])
        after_acts = current_activities(base, [e for e in events if e.id <= event.id])
        before = schedule_with_materials(before_acts, materials, start_date)
        after = schedule_with_materials(after_acts, materials, start_date)
        # Recalculated now, not taken from when the option was proposed: the plan
        # may have changed since (e.g. a material was linked).
        deliveries = [e for e in option.edits if e.type == "change_delivery"]
        _, asked, _ = apply_edits(deliveries, after_acts, materials, event.created_at.date())
        expected = schedule_with_materials(after_acts, asked, start_date)

        messages = []
        found = recipients(option, contacts, materials, after_acts, before, after, expected)
        for contact, facts in found:
            text = draft(project, option, contact, facts)
            body = text.body.rstrip() + "\n\nKey facts:\n" + "\n".join(f"- {f}" for f in facts)
            messages.append(
                {"to": contact.email, "name": contact.name, "role": contact.role,
                 "subject": text.subject, "body": body}
            )  # fmt: skip
        payload = {"option_event": event.id, "title": option.title, "messages": messages}
        return [Emit(ACTION_PLAN_DRAFTED, payload)]

    return handle


def choose_option(options_event: Event, number: int) -> Emit:
    """A planner picks option `number` (1-based) from a RecoveryOptionsProposed event."""
    option = options_event.payload["options"][number - 1]
    return Emit(OPTION_CHOSEN, {"options_event": options_event.id, "option": option})
