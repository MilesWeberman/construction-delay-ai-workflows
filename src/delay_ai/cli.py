"""Command line entry point: `uv run delay-ai <ingest|link|choose|outbox>`."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from delay_ai.actions import choose_option, draft_with_llm, make_action_handler
from delay_ai.cpm import compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    ACTION_PLAN_DRAFTED,
    DELAY_ASSESSED,
    DELIVERY_DATE_CHANGED,
    EMAIL_RECEIVED,
    MATERIAL_LINKED,
    MATERIAL_ORDERED,
    NEEDS_REVIEW,
    OPTION_CHOSEN,
    RECOVERY_OPTIONS_PROPOSED,
    EventStore,
)
from delay_ai.extraction import extract_with_llm
from delay_ai.impact import make_impact_handler
from delay_ai.ingestion import make_email_handler
from delay_ai.linking import make_link_handler, planner_link, suggest_with_llm
from delay_ai.loaders import load_contacts, load_project, load_schedule
from delay_ai.materials import build_materials, pending_link_suggestions
from delay_ai.orchestrator import Orchestrator, ingest_emails
from delay_ai.planner import make_planner_handler, propose_with_llm


def handlers(store: EventStore, data: Path) -> dict:
    activities = load_schedule(data / "schedule.csv")
    project = load_project(data / "project.json")
    start_date = project.start_date
    contacts = load_contacts(data / "contacts.csv")
    schedule = compute_schedule(activities, start_date)
    impact = make_impact_handler(store, activities, start_date)
    return {
        EMAIL_RECEIVED: make_email_handler(store, extract_with_llm),
        MATERIAL_ORDERED: make_link_handler(activities, schedule, suggest_with_llm),
        DELIVERY_DATE_CHANGED: impact,
        MATERIAL_LINKED: impact,
        DELAY_ASSESSED: make_planner_handler(store, activities, start_date, propose_with_llm),
        OPTION_CHOSEN: make_action_handler(
            store, activities, start_date, contacts, project.name, draft_with_llm
        ),
    }


def ingest(store: EventStore, data: Path, emails: Path) -> None:
    print(f"{ingest_emails(FolderEmailSource(emails), store)} new emails")
    print(f"{store.retry_failed()} failed events retried")
    Orchestrator(store, handlers(store, data)).run()
    report(store)


def report(store: EventStore) -> None:
    events = store.all()
    print("\nMaterials:")
    for m in build_materials(events):
        activity = m.activity_id or "unlinked"
        print(
            f"  {m.po_number}  {m.planned_delivery}  {activity:<8}  {m.supplier}: {m.description}"
        )
    print("\nLinks to confirm (delay-ai link <PO> <activity>):")
    for e in pending_link_suggestions(events):
        p = e.payload
        print(f"  {p['po_number']}: rules {p['by_rules']}, LLM {p['by_llm']} - {p['rationale']}")
    print("\nDelays:")
    for e in events:
        if e.type == DELAY_ASSESSED:
            p = e.payload
            effect = (
                f"project +{p['project_slip_days']} days, finish {p['new_finish']}"
                if p["project_slip_days"] > 0
                else "finish unchanged"
            )
            moved = f"{p['old_delivery']} -> {p['new_delivery']}"
            print(f"  {p['po_number']} ({p['activity_id']}): {moved}, {effect}")
    print("\nRecovery options:")
    for e in events:
        if e.type == RECOVERY_OPTIONS_PROPOSED:
            print(f"  For {e.payload['po_number']} (event {e.id}):")
            for n, o in enumerate(e.payload["options"], start=1):
                print(
                    f"    {n}. {o['title']}: recovers {o['recovered_days']} days, "
                    f"finish {o['new_finish']}. Cost: {o['cost']}"
                )
                print(f"       {o['rationale']}")
                print(f"       Risks: {o['risks']}")
            for r in e.payload["rejected"]:
                print(f"    Rejected: {r['title']} ({'; '.join(r['problems'])})")
    print("  Choose one with: delay-ai choose <event> <number>")
    print("\nAction plans drafted (delay-ai outbox):")
    for e in events:
        if e.type == ACTION_PLAN_DRAFTED:
            print(f"  {e.payload['title']}: {len(e.payload['messages'])} messages")
    print("\nNeeds review:")
    for e in events:
        if e.type == NEEDS_REVIEW:
            print(f"  {e.payload['source_email']}: {'; '.join(e.payload['problems'])}")
    print("\nFailed:")
    for e in events:
        if e.status == "failed":
            print(f"  event {e.id} ({e.type}): {e.error}")


def link(store: EventStore, data: Path, po_number: str, activity_id: str) -> None:
    if po_number not in {m.po_number for m in build_materials(store.all())}:
        sys.exit(f"Unknown PO: {po_number}")
    if activity_id not in {a.id for a in load_schedule(data / "schedule.csv")}:
        sys.exit(f"Unknown activity: {activity_id}")
    emit = planner_link(po_number, activity_id)
    store.append(emit.type, emit.payload)
    print(f"Linked {po_number} to {activity_id}")
    Orchestrator(store, handlers(store, data)).run()
    report(store)


def choose(store: EventStore, data: Path, options_event: int, number: int) -> None:
    event = store.get(options_event)
    if event.type != RECOVERY_OPTIONS_PROPOSED or not 1 <= number <= len(event.payload["options"]):
        sys.exit(f"No option {number} in event {options_event}")
    emit = choose_option(event, number)
    store.append(emit.type, emit.payload)
    print(f"Chose: {emit.payload['option']['title']}")
    Orchestrator(store, handlers(store, data)).run()
    outbox(store)


def outbox(store: EventStore) -> None:
    """Print every drafted message. Nothing is sent."""
    for e in store.all():
        if e.type != ACTION_PLAN_DRAFTED:
            continue
        print(f"=== Action plan: {e.payload['title']} ===")
        for m in e.payload["messages"]:
            print(f"\nTo: {m['name']} ({m['role']}) <{m['to']}>")
            print(f"Subject: {m['subject']}\n")
            print(m["body"])
        print()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="delay-ai")
    parser.add_argument("--db", type=Path, default=Path("data/local/events.db"))
    parser.add_argument("--data", type=Path, default=Path("data/sample"), help="project files")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_cmd = commands.add_parser("ingest", help="Read emails and update the materials table")
    ingest_cmd.add_argument("--emails", type=Path, default=Path("data/sample/emails"))
    link_cmd = commands.add_parser("link", help="Confirm which activity needs a material")
    link_cmd.add_argument("po_number")
    link_cmd.add_argument("activity_id")
    choose_cmd = commands.add_parser("choose", help="Pick a recovery option and draft actions")
    choose_cmd.add_argument("options_event", type=int)
    choose_cmd.add_argument("number", type=int)
    commands.add_parser("outbox", help="Show drafted messages (nothing is sent)")
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = EventStore(args.db)
    if args.command == "ingest":
        ingest(store, args.data, args.emails)
    elif args.command == "link":
        link(store, args.data, args.po_number, args.activity_id)
    elif args.command == "choose":
        choose(store, args.data, args.options_event, args.number)
    elif args.command == "outbox":
        outbox(store)
