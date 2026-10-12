"""Everything the web page shows, built from the events as plain JSON-ready dicts."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from delay_ai.cpm import add_working_days, compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    ACTION_PLAN_DRAFTED,
    CHAT_MESSAGE_RECEIVED,
    CHAT_REPLIED,
    DELAY_ASSESSED,
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    DISRUPTION_ASSESSED,
    EMAIL_IGNORED,
    EMAIL_RECEIVED,
    MATERIAL_ORDERED,
    MESSAGE_SENT,
    NEEDS_REVIEW,
    OPTION_CHOSEN,
    RECOVERY_OPTIONS_PROPOSED,
    Event,
)
from delay_ai.impact import schedule_with_materials
from delay_ai.loaders import load_project, load_schedule
from delay_ai.materials import build_materials, pending_link_suggestions
from delay_ai.plan import current_activities
from delay_ai.review import open_reviews


def of_type(events: list[Event], *types: str) -> list[Event]:
    return [e for e in events if e.type in types]


def capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]


def build_view(events: list[Event], data: Path) -> dict[str, Any]:
    project = load_project(data / "project.json")
    base = load_schedule(data / "schedule.csv")
    activities = current_activities(base, events)
    names = {a.id: a.name for a in activities}
    materials = build_materials(events)
    by_po = {m.po_number: m for m in materials}
    schedule = schedule_with_materials(activities, materials, project.start_date)
    original = compute_schedule(base, project.start_date)
    proposals = of_type(events, RECOVERY_OPTIONS_PROPOSED)
    chosen = {e.payload["options_event"]: e for e in of_type(events, OPTION_CHOSEN)}

    def options(proposal: Event) -> dict[str, Any]:
        choice = chosen.get(proposal.id)
        return {
            "event": proposal.id,
            "chosen": choice.payload["option"]["title"] if choice else None,
            "options": [
                {"number": n, **{k: o[k] for k in ("title", "recovered_days", "new_finish",
                                                    "cost", "rationale", "risks")}}
                for n, o in enumerate(proposal.payload["options"], start=1)
            ],
        }  # fmt: skip

    alerts, absorbed = [], []
    delays = of_type(events, DELAY_ASSESSED, DISRUPTION_ASSESSED)
    for delay in delays:
        p = delay.payload
        if delay.type == DELAY_ASSESSED:
            name = capitalised(by_po[p["po_number"]].description)
            headline = (
                f"{name} now arrives {date.fromisoformat(p['new_delivery']):%d %b} "
                f"instead of {date.fromisoformat(p['old_delivery']):%d %b}"
            )
        else:
            name = headline = capitalised(p["summary"])
        if p["project_slip_days"] <= 0:
            absorbed.append(name)
            continue
        recovery = next(
            (options(x) for x in proposals if x.payload.get("assessment_event") == delay.id), None
        )
        alerts.append(
            {"kind": "delay", "headline": headline, "slip_days": p["project_slip_days"],
             "recovery": recovery}
        )  # fmt: skip
    for proposal in proposals:
        if proposal.payload.get("chat_event"):  # a change suggested in the chat
            alerts.append(
                {"kind": "suggestion", "headline": "Your suggested change", "slip_days": 0,
                 "recovery": options(proposal)}
            )  # fmt: skip

    links = [
        {
            "po": s.payload["po_number"],
            "material": capitalised(by_po[s.payload["po_number"]].description),
            "supplier": by_po[s.payload["po_number"]].supplier,
            "delivery": str(by_po[s.payload["po_number"]].planned_delivery),
            "suggested": s.payload["by_llm"] or s.payload["by_rules"],
        }
        for s in pending_link_suggestions(events)
    ]

    moved = {e.payload["po_number"] for e in of_type(events, DELIVERY_DATE_CHANGED)}
    calendar = []
    for a in activities:
        s = schedule.activities[a.id]
        start = schedule.start_of(a.id)
        end = add_working_days(project.start_date, max(s.early_finish - 1, 0)) + timedelta(days=1)
        calendar.append(
            {"title": a.name, "start": str(start), "end": str(max(end, start)), "kind": "activity"}
        )
    for m in materials:
        kind = "delivery_moved" if m.po_number in moved else "delivery"
        calendar.append(
            {
                "title": capitalised(m.description),
                "start": str(m.planned_delivery),
                "end": None,
                "kind": kind,
            }
        )
    first = next((d for d in delays if d.payload["project_slip_days"] > 0), None)
    calendar_start = (
        schedule.start_of(first.payload["delayed_activities"][0]) if first else project.start_date
    )

    received = {e.payload["message_id"]: e for e in of_type(events, EMAIL_RECEIVED)}
    unsettled = {e.payload["source_email"]: e for e in open_reviews(events)}

    def domain(address: str) -> str:
        return address.rsplit("@", 1)[-1]

    def read_as(email_id: str, email_event: Event | None) -> tuple[str, str]:
        """(status, label) for what the AI made of an email."""
        found = [e for e in events if email_event and e.caused_by == email_event.id]
        types = {e.type for e in found}
        if NEEDS_REVIEW in types:
            return (
                ("review", "Needs your review")
                if email_id in unsettled
                else ("reviewed", "Reviewed")
            )
        for e in found:
            if e.type == DELIVERY_DATE_CHANGED:
                new = date.fromisoformat(e.payload["new_delivery"])
                return "moved", f"Delivery moved to {new:%d %b}"
            if e.type == DELIVERY_CONFIRMED:
                return "confirmed", "Delivery confirmed on time"
            if e.type == EMAIL_IGNORED:
                return "ignored", "Not about deliveries"
        orders = of_type(found, MATERIAL_ORDERED)
        if orders:
            return "orders", f"Added {len(orders)} deliver{'ies' if len(orders) > 1 else 'y'}"
        return "pending", "Not read yet"

    inbox = []
    for email in reversed(FolderEmailSource(data / "emails").fetch()):
        status, label = read_as(email.message_id, received.get(email.message_id))
        review = None
        if status == "review":
            flagged = unsettled[email.message_id].payload
            items = flagged["extraction"]["items"]
            candidates = [m for m in materials if domain(m.supplier_email) == domain(email.sender)]
            suggested = next((i["po_number"] for i in items if i["po_number"] in by_po), None)
            review = {
                "problems": flagged["problems"],
                "suggested_po": suggested or (candidates[0].po_number if candidates else None),
                "candidates": [
                    {"po": m.po_number, "material": capitalised(m.description),
                     "delivery": str(m.planned_delivery)}
                    for m in candidates
                ],
            }  # fmt: skip
        inbox.append(
            {"id": email.message_id, "date": email.sent_at.isoformat(), "from": email.sender,
             "subject": email.subject, "body": email.body, "status": status, "label": label,
             "review": review}
        )  # fmt: skip

    # Materials: what the supplier last said, and what it does to completion.
    first_planned, latest_news, latest_effect = {}, {}, {}
    for e in of_type(events, MATERIAL_ORDERED):
        m = e.payload["material"]
        first_planned[m["po_number"]] = m["planned_delivery"]
    for e in of_type(events, DELIVERY_CONFIRMED, DELIVERY_DATE_CHANGED):
        latest_news[e.payload["po_number"]] = e.type
    for e in of_type(events, DELAY_ASSESSED):
        latest_effect[e.payload["po_number"]] = e
    recovered = {p.payload.get("assessment_event") for p in proposals if p.id in chosen}

    def material_status(m) -> tuple[str, str]:
        if latest_news.get(m.po_number) == DELIVERY_DATE_CHANGED:
            effect = latest_effect.get(m.po_number)
            if effect is None:
                return "late_unchecked", "Late: not checked yet"
            slip = effect.payload["project_slip_days"]
            if slip <= 0:
                return "late_absorbed", "Late: no effect on completion"
            if effect.id in recovered:
                return "late_recovered", "Late: recovery chosen"
            return "late_slips", f"Late: completion +{slip} days"
        if latest_news.get(m.po_number) == DELIVERY_CONFIRMED:
            return "confirmed", "Confirmed by supplier"
        if m.activity_id is None:
            return "unmatched", "Not matched to a task"
        return "on_track", "On track"

    sent = {e.payload["message_id"] for e in of_type(events, MESSAGE_SENT)}
    outbox = [
        {**m, "id": f"{e.id}:{i}", "plan": e.payload["title"], "sent": f"{e.id}:{i}" in sent}
        for e in reversed(of_type(events, ACTION_PLAN_DRAFTED))
        for i, m in enumerate(e.payload["messages"])
    ]

    replies = {e.payload["chat_event"]: e for e in of_type(events, CHAT_REPLIED)}
    chat = []
    for e in of_type(events, CHAT_MESSAGE_RECEIVED):
        chat.append({"role": "user", "text": e.payload["body"]})
        if e.id in replies:
            chat.append({"role": "assistant", "text": replies[e.id].payload["text"]})

    return {
        "project": {"name": project.name, "location": project.location},
        "completion": {
            "date": str(schedule.finish_date),
            "planned": str(original.finish_date),
            "slip_days": schedule.duration_days - original.duration_days,
        },
        "alerts": alerts,
        "absorbed": absorbed,
        "links": links,
        "activities": [{"id": a.id, "name": a.name} for a in activities],
        "calendar": calendar,
        "calendar_start": str(calendar_start),
        "inbox": inbox,
        "materials": [
            {
                "po": m.po_number,
                "material": capitalised(m.description),
                "supplier": m.supplier,
                "delivery": str(m.planned_delivery),
                "was": first_planned[m.po_number]
                if first_planned.get(m.po_number) != str(m.planned_delivery)
                else None,
                "status": material_status(m)[0],
                "label": material_status(m)[1],
                "needed_for": names.get(m.activity_id or ""),
            }
            for m in materials
        ],
        "outbox": outbox,
        "counts": {
            "review": len(unsettled),
            "drafts": sum(not m["sent"] for m in outbox),
        },
        "chat": chat,
    }
