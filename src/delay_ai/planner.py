"""Recovery options for a delay: the LLM proposes schedule edits, the CPM scores them."""

from collections.abc import Callable
from datetime import date

from pydantic import BaseModel, Field

from delay_ai import knowledge
from delay_ai.cpm import Schedule
from delay_ai.events import RECOVERY_OPTIONS_PROPOSED, Emit, Event, EventStore
from delay_ai.impact import DeliveryImpact, schedule_with_materials
from delay_ai.llm import complete_structured
from delay_ai.materials import build_materials
from delay_ai.models import Activity, Material
from delay_ai.plan import Edit, apply_edits, current_activities


class RecoveryOption(BaseModel):
    title: str
    edits: list[Edit]
    rationale: str
    risks: str
    cost: str = Field(description="Rough cost or effort, e.g. 'two extra gangs, about £15k'")


class RecoveryPlan(BaseModel):
    options: list[RecoveryOption]


class EvaluatedOption(RecoveryOption):
    recovered_days: int
    new_finish: date


def describe_plan(schedule: Schedule, activities: list[Activity], materials: list[Material]) -> str:
    lines = ["Programme (working days, Mon-Fri):"]
    for a in activities:
        s = schedule.activities[a.id]
        flag = "CRITICAL" if s.is_critical else f"float {s.total_float}"
        after = ", ".join(a.predecessors) or "-"
        lines.append(
            f"- {a.id} {a.name} ({a.trade}), {a.duration_days}d, after {after}, "
            f"starts {schedule.start_of(a.id)}, {flag}"
        )
    lines.append("\nMaterials:")
    for m in materials:
        lines.append(
            f"- {m.po_number} {m.description} from {m.supplier}, for {m.activity_id}, "
            f"delivery {m.planned_delivery}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You are a senior UK construction planner. A late delivery has
pushed out the project finish. Propose up to 3 distinct recovery options.

Each option is a list of edits to the programme:
- remove_dependency: let activity_id start without waiting for predecessor_id
- shorten: take days off activity_id (extra labour, longer shifts)
- change_delivery: ask the supplier of po_number to deliver earlier, on new_delivery

The days recovered are calculated for you afterwards, so don't state them.
Explain the rationale in planning terms, be honest about risks, and give a rough
cost. Use this context, and follow the playbook:

{knowledge.load()}"""


def propose_with_llm(
    impact: DeliveryImpact,
    schedule: Schedule,
    activities: list[Activity],
    materials: list[Material],
) -> RecoveryPlan:
    user = f"""Delay: {impact.po_number} for {impact.activity_id} moved from {impact.old_delivery}
to {impact.new_delivery}. The finish moved from {impact.old_finish} to {impact.new_finish}
({impact.project_slip_days} working days).

{describe_plan(schedule, activities, materials)}"""
    return complete_structured(SYSTEM_PROMPT, user, RecoveryPlan)


Proposer = Callable[[DeliveryImpact, Schedule, list[Activity], list[Material]], RecoveryPlan]


def make_planner_handler(
    store: EventStore, base: list[Activity], start_date: date, propose: Proposer
) -> Callable[[Event], list[Emit]]:
    def handle(event: Event) -> list[Emit]:
        impact = DeliveryImpact.model_validate(event.payload)
        if impact.project_slip_days <= 0:
            return []
        events = store.all()
        materials = build_materials(events)
        activities = current_activities(base, events)
        current = schedule_with_materials(activities, materials, start_date)
        plan = propose(impact, current, activities, materials)

        options, rejected = [], []
        for option in plan.options:
            new_acts, new_mats, problems = apply_edits(
                option.edits, activities, materials, event.created_at.date()
            )
            if problems:
                rejected.append({"title": option.title, "problems": problems})
                continue
            result = schedule_with_materials(new_acts, new_mats, start_date)
            options.append(
                EvaluatedOption(
                    **option.model_dump(),
                    recovered_days=current.duration_days - result.duration_days,
                    new_finish=result.finish_date,
                )
            )
        options.sort(key=lambda o: o.recovered_days, reverse=True)
        payload = {
            "assessment_event": event.id,
            "po_number": impact.po_number,
            "options": [o.model_dump(mode="json") for o in options],
            "rejected": rejected,
        }
        return [Emit(RECOVERY_OPTIONS_PROPOSED, payload)]

    return handle
