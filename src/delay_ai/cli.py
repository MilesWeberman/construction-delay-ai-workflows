"""Command line entry point: `uv run delay-ai ingest` and `uv run delay-ai link`."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from delay_ai.cpm import compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    DELAY_ASSESSED,
    DELIVERY_DATE_CHANGED,
    EMAIL_RECEIVED,
    MATERIAL_LINKED,
    MATERIAL_ORDERED,
    NEEDS_REVIEW,
    RECOVERY_OPTIONS_PROPOSED,
    EventStore,
)
from delay_ai.extraction import extract_with_llm
from delay_ai.impact import make_impact_handler
from delay_ai.ingestion import make_email_handler
from delay_ai.linking import make_link_handler, planner_link, suggest_with_llm
from delay_ai.loaders import load_project, load_schedule
from delay_ai.materials import build_materials, pending_link_suggestions
from delay_ai.orchestrator import Orchestrator, ingest_emails
from delay_ai.planner import make_planner_handler, propose_with_llm


def handlers(store: EventStore, data: Path) -> dict:
    activities = load_schedule(data / "schedule.csv")
    start_date = load_project(data / "project.json").start_date
    schedule = compute_schedule(activities, start_date)
    impact = make_impact_handler(store, activities, start_date)
    return {
        EMAIL_RECEIVED: make_email_handler(store, extract_with_llm),
        MATERIAL_ORDERED: make_link_handler(activities, schedule, suggest_with_llm),
        DELIVERY_DATE_CHANGED: impact,
        MATERIAL_LINKED: impact,
        DELAY_ASSESSED: make_planner_handler(store, activities, start_date, propose_with_llm),
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
                else "absorbed by float"
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
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = EventStore(args.db)
    if args.command == "ingest":
        ingest(store, args.data, args.emails)
    elif args.command == "link":
        link(store, args.data, args.po_number, args.activity_id)
