"""Command line entry point: `uv run delay-ai <ingest|chat|link|choose|outbox>`."""

import argparse
import fcntl
import json
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from delay_ai.actions import choose_option
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    ACTION_PLAN_DRAFTED,
    CHAT_REPLIED,
    DELAY_ASSESSED,
    DISRUPTION_ASSESSED,
    NEEDS_REVIEW,
    OPTION_CHOSEN,
    RECOVERY_OPTIONS_PROPOSED,
    EventStore,
)
from delay_ai.linking import planner_link
from delay_ai.llm import missing_api_key, model
from delay_ai.loaders import load_schedule
from delay_ai.materials import build_materials, pending_link_suggestions
from delay_ai.orchestrator import Orchestrator, ingest_chat, ingest_emails
from delay_ai.workflow import handlers


def run(store: EventStore, data: Path) -> None:
    """Process everything pending, printing each step as it finishes (LLM calls take a while)."""
    print("Working (each LLM step takes a few seconds, recovery options up to a minute):")
    Orchestrator(store, handlers(store, data), on_step=lambda m: print(f"  {m}", flush=True)).run()


def ingest(store: EventStore, data: Path, emails: Path) -> None:
    print(f"{ingest_emails(FolderEmailSource(emails), store)} new emails")
    print(f"{store.retry_failed()} failed events retried")
    run(store, data)
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
    for e in events:
        if e.type == DISRUPTION_ASSESSED:
            p = e.payload
            effect = (
                f"project +{p['project_slip_days']} days, finish {p['new_finish']}"
                if p["project_slip_days"] > 0
                else "finish unchanged"
            )
            print(f"  Site news: {p['summary']}, {effect}")
    print("\nRecovery options:")
    for e in events:
        if e.type == RECOVERY_OPTIONS_PROPOSED:
            about = e.payload["po_number"] or "site news or a change suggested in chat"
            print(f"  For {about} (event {e.id}):")
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


def chat(store: EventStore, data: Path, text: str, author: str) -> None:
    message = ingest_chat(text, author, store)
    run(store, data)
    report(store)
    for e in store.all():
        if e.type == CHAT_REPLIED and e.payload["chat_event"] == message.id:
            print(f"\nAssistant: {e.payload['text']}")


def link(store: EventStore, data: Path, po_number: str, activity_id: str) -> None:
    if po_number not in {m.po_number for m in build_materials(store.all())}:
        sys.exit(f"Unknown PO: {po_number}")
    if activity_id not in {a.id for a in load_schedule(data / "schedule.csv")}:
        sys.exit(f"Unknown activity: {activity_id}")
    emit = planner_link(po_number, activity_id)
    store.append(emit.type, emit.payload)
    print(f"Linked {po_number} to {activity_id}")
    run(store, data)
    report(store)


def choose(store: EventStore, data: Path, options_event: int, number: int) -> None:
    event = store.get(options_event)
    if event.type != RECOVERY_OPTIONS_PROPOSED or not 1 <= number <= len(event.payload["options"]):
        sys.exit(f"No option {number} in event {options_event}")
    if any(
        e.type == OPTION_CHOSEN and e.payload["options_event"] == options_event for e in store.all()
    ):
        sys.exit(f"An option for event {options_event} has already been chosen")
    emit = choose_option(event, number)
    store.append(emit.type, emit.payload)
    print(f"Chose: {emit.payload['option']['title']}")
    run(store, data)
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


def seed(data: Path, emails: Path, out: Path) -> None:
    """Run the sample inbox once on a fresh database and save the events, so the app
    can start from them without any LLM calls."""
    with tempfile.TemporaryDirectory() as folder:
        store = EventStore(Path(folder) / "seed.db")
        ingest(store, data, emails)
        events = store.export()
    out.write_text(json.dumps(events, indent=1) + "\n")
    print(f"\nSaved {len(events)} events to {out}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="delay-ai")
    parser.add_argument("--db", type=Path, default=Path("data/local/events.db"))
    parser.add_argument("--data", type=Path, default=Path("data/sample"), help="project files")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_cmd = commands.add_parser("ingest", help="Read emails and update the materials table")
    ingest_cmd.add_argument("--emails", type=Path, default=Path("data/sample/emails"))
    chat_cmd = commands.add_parser(
        "chat", help="Delivery news, a suggested schedule change, or a question"
    )
    chat_cmd.add_argument("text")
    chat_cmd.add_argument("--author", default="Site team")
    link_cmd = commands.add_parser("link", help="Confirm which activity needs a material")
    link_cmd.add_argument("po_number")
    link_cmd.add_argument("activity_id")
    choose_cmd = commands.add_parser("choose", help="Pick a recovery option and draft actions")
    choose_cmd.add_argument("options_event", type=int)
    choose_cmd.add_argument("number", type=int)
    commands.add_parser("outbox", help="Show drafted messages (nothing is sent)")
    seed_cmd = commands.add_parser("seed", help="Cache the sample run for the app")
    seed_cmd.add_argument("--emails", type=Path, default=Path("data/sample/emails"))
    seed_cmd.add_argument("--out", type=Path, default=Path("data/sample/seed_events.json"))
    args = parser.parse_args()

    if args.command in {"ingest", "chat", "link", "choose", "seed"} and (key := missing_api_key()):
        sys.exit(f"{key} is not set for model {model()}. Add it to .env (see README > Setup).")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    # One run at a time: two runs would both process the same pending events.
    lock = args.db.with_suffix(".lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Another delay-ai run is using this database. Try again when it finishes.")
    store = EventStore(args.db)
    if args.command == "ingest":
        ingest(store, args.data, args.emails)
    elif args.command == "chat":
        chat(store, args.data, args.text, args.author)
    elif args.command == "link":
        link(store, args.data, args.po_number, args.activity_id)
    elif args.command == "choose":
        choose(store, args.data, args.options_event, args.number)
    elif args.command == "outbox":
        outbox(store)
    elif args.command == "seed":
        seed(args.data, args.emails, args.out)
