"""Web API for the React app: `uv run delay-ai serve`.

The server keeps no state. Every visitor starts from the cached sample run
(seed_events.json); the browser keeps the visitor's own events (everything after
the seed) in localStorage and sends them with each request. The server replays
seed + visitor events in memory, runs any action, and returns the page data and
the visitor's events to store again.
"""

import hashlib
import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from delay_ai.actions import choose_option
from delay_ai.events import OPTION_CHOSEN, RECOVERY_OPTIONS_PROPOSED, EventStore
from delay_ai.linking import planner_link
from delay_ai.llm import missing_api_key
from delay_ai.orchestrator import Orchestrator, ingest_chat
from delay_ai.review import dismiss_review, enter_delivery_date, mark_sent
from delay_ai.view import build_view
from delay_ai.workflow import handlers

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "sample"
WEB_BUILD = ROOT / "web" / "dist"

load_dotenv()
app = FastAPI(title="Delay AI")


@cache
def seed() -> tuple[list[dict[str, Any]], str, int]:
    text = (DATA / "seed_events.json").read_text()
    events = json.loads(text)
    return events, hashlib.sha256(text.encode()).hexdigest()[:12], max(e["id"] for e in events)


class Link(BaseModel):
    kind: Literal["link"]
    links: list[tuple[str, str]]  # (PO, activity id)


class Choose(BaseModel):
    kind: Literal["choose"]
    options_event: int
    number: int


class Chat(BaseModel):
    kind: Literal["chat"]
    text: str = Field(min_length=1, max_length=2000)


class SetDelivery(BaseModel):
    kind: Literal["set_delivery"]
    email_id: str
    po_number: str
    date: date


class DismissReview(BaseModel):
    kind: Literal["dismiss_review"]
    email_id: str


class MarkSent(BaseModel):
    kind: Literal["mark_sent"]
    message_id: str


Action = Link | Choose | Chat | SetDelivery | DismissReview | MarkSent
NEEDS_AI = (Choose, Chat)


class Request(BaseModel):
    seed: str | None = None  # the seed the visitor's events were made on
    events: list[dict[str, Any]] = []
    action: Annotated[Action, Field(discriminator="kind")] | None = None


def replay(request: Request) -> tuple[EventStore, str, int]:
    events, seed_hash, last_seed_id = seed()
    store = EventStore()
    store.load(events)
    if request.seed == seed_hash:  # events made on an older seed are dropped
        try:
            store.load([e for e in request.events if e["id"] > last_seed_id])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"Saved events are invalid: {e}") from e
    return store, seed_hash, last_seed_id


def run(store: EventStore, action: Action) -> None:
    if isinstance(action, NEEDS_AI) and (key := missing_api_key()):
        raise HTTPException(503, f"{key} is not set on the server, so the AI can't run")
    if isinstance(action, Link):
        for po_number, activity_id in action.links:
            emit = planner_link(po_number, activity_id)
            store.append(emit.type, emit.payload)
    elif isinstance(action, Choose):
        proposal = store.get(action.options_event)
        already = any(
            e.type == OPTION_CHOSEN and e.payload["options_event"] == proposal.id
            for e in store.all()
        )
        if proposal.type != RECOVERY_OPTIONS_PROPOSED or already:
            raise HTTPException(400, "That option can't be chosen")
        emit = choose_option(proposal, action.number)
        store.append(emit.type, emit.payload)
    elif isinstance(action, Chat):
        ingest_chat(action.text, "You", store)
    elif isinstance(action, SetDelivery):
        try:
            emits = enter_delivery_date(
                store.all(), action.email_id, action.po_number, action.date, date.today()
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        for emit in emits:
            store.append(emit.type, emit.payload)
    else:
        emit = (
            dismiss_review(action.email_id)
            if isinstance(action, DismissReview)
            else mark_sent(action.message_id)
        )
        store.append(emit.type, emit.payload)
    Orchestrator(store, handlers(store, DATA)).run()


@app.post("/api/view")
def view(request: Request) -> dict[str, Any]:
    """The page data, after running the action if there is one."""
    store, seed_hash, last_seed_id = replay(request)
    if request.action:
        run(store, request.action)
    return {
        "seed": seed_hash,
        "events": store.export(after_id=last_seed_id),
        "view": build_view(store.all(), DATA) | {"ai_ready": missing_api_key() is None},
    }


if WEB_BUILD.exists():  # the built React app, so one command serves everything
    app.mount("/", StaticFiles(directory=WEB_BUILD, html=True), name="web")
