"""Web API for the React app: `uv run delay-ai serve`.

The server keeps no state. Every visitor starts from the cached sample run
(seed_events.json); the browser keeps the visitor's own events (everything after
the seed) in localStorage and sends them with each request. The server replays
seed + visitor events in memory, runs any action, and returns the page data and
the visitor's events to store again.
"""

import base64
import hashlib
import json
import os
import secrets
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi import Request as HttpRequest
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from delay_ai.actions import choose_option
from delay_ai.events import (
    DELAY_ASSESSED,
    DISRUPTION_ASSESSED,
    OPTION_CHOSEN,
    RECOVERY_OPTIONS_PROPOSED,
    Event,
    EventStore,
)
from delay_ai.linking import planner_link
from delay_ai.llm import missing_api_key
from delay_ai.orchestrator import Orchestrator, ingest_chat
from delay_ai.review import dismiss_review, enter_delivery_date, mark_sent
from delay_ai.view import build_view
from delay_ai.workflow import handlers

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "sample"
WEB_BUILD = ROOT / "web" / "dist"
DELAYS = {DELAY_ASSESSED, DISRUPTION_ASSESSED}

load_dotenv()
app = FastAPI(title="Delay AI")
# Set to put the whole app behind one shared password (the browser asks for it).
PASSWORD = os.environ.get("DEMO_PASSWORD", "")


@app.middleware("http")
async def require_password(request: HttpRequest, call_next):
    if not PASSWORD or request.url.path == "/api/health":
        return await call_next(request)
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    try:
        _, _, given = base64.b64decode(encoded).decode().partition(":")
    except ValueError:
        given = ""
    if scheme.lower() == "basic" and secrets.compare_digest(given.encode(), PASSWORD.encode()):
        return await call_next(request)
    return Response(
        "Password required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Delay AI"'}
    )


@app.get("/api/health")
def health() -> dict[str, bool]:
    """For the host's health check; never needs the password."""
    return {"ok": True}


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


class Continue(BaseModel):
    """Run the work left pending by the previous request (recovery options)."""

    kind: Literal["continue"]


Action = Link | Choose | Chat | SetDelivery | DismissReview | MarkSent | Continue
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


def needs_recovery_options(event: Event) -> bool:
    """A delay that moves completion: the planner's LLM call takes up to a minute, so
    the app replies first and asks for these in a follow-up `continue` request."""
    return event.type in DELAYS and event.payload["project_slip_days"] > 0


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
    elif isinstance(action, (DismissReview, MarkSent)):
        emit = (
            dismiss_review(action.email_id)
            if isinstance(action, DismissReview)
            else mark_sent(action.message_id)
        )
        store.append(emit.type, emit.payload)
    defer = None if isinstance(action, Continue) else needs_recovery_options
    Orchestrator(store, handlers(store, DATA)).run(defer=defer)


@app.post("/api/view")
def view(request: Request) -> dict[str, Any]:
    """The page data, after running the action if there is one."""
    store, seed_hash, last_seed_id = replay(request)
    if request.action:
        run(store, request.action)
    return {
        "seed": seed_hash,
        "events": store.export(after_id=last_seed_id),
        "view": build_view(store.all(), DATA)
        | {
            "ai_ready": missing_api_key() is None,
            "pending_work": any(needs_recovery_options(e) for e in store.pending()),
        },
    }


if WEB_BUILD.exists():  # the built React app, so one command serves everything
    app.mount("/", StaticFiles(directory=WEB_BUILD, html=True), name="web")
