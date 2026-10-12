"""Command line entry point: `uv run delay-ai ingest`."""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from delay_ai.email_source import FolderEmailSource
from delay_ai.events import EMAIL_RECEIVED, NEEDS_REVIEW, EventStore
from delay_ai.extraction import extract_with_llm
from delay_ai.ingestion import make_email_handler
from delay_ai.materials import build_materials
from delay_ai.orchestrator import Orchestrator, ingest_emails


def ingest(emails: Path, db: Path) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    store = EventStore(db)
    print(f"{ingest_emails(FolderEmailSource(emails), store)} new emails")
    print(f"{store.retry_failed()} failed events retried")
    Orchestrator(store, {EMAIL_RECEIVED: make_email_handler(store, extract_with_llm)}).run()

    events = store.all()
    print("\nMaterials:")
    for m in build_materials(events):
        print(f"  {m.po_number}  {m.planned_delivery}  {m.supplier}: {m.description}")
    print("\nNeeds review:")
    for e in events:
        if e.type == NEEDS_REVIEW:
            print(f"  {e.payload['source_email']}: {'; '.join(e.payload['problems'])}")
    print("\nFailed:")
    for e in events:
        if e.status == "failed":
            print(f"  event {e.id} ({e.type}): {e.error}")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="delay-ai")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_cmd = commands.add_parser("ingest", help="Read emails and update the materials table")
    ingest_cmd.add_argument("--emails", type=Path, default=Path("data/sample/emails"))
    ingest_cmd.add_argument("--db", type=Path, default=Path("data/local/events.db"))
    args = parser.parse_args()
    if args.command == "ingest":
        ingest(args.emails, args.db)
