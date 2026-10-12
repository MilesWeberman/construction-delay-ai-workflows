"""Runs pending events through their handlers until nothing is left to do."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from delay_ai.email_source import EmailSource
from delay_ai.events import CHAT_MESSAGE_RECEIVED, EMAIL_RECEIVED, Emit, Event, EventStore
from delay_ai.models import Email

Handler = Callable[[Event], list[Emit]]


class Orchestrator:
    def __init__(
        self,
        store: EventStore,
        handlers: dict[str, Handler],
        on_step: Callable[[str], None] | None = None,
    ):
        self.store = store
        self.handlers = handlers
        self.on_step = on_step or (lambda message: None)  # progress, e.g. print

    def run(self, max_steps: int = 1000) -> int:
        """Process events (including newly emitted ones) until none are pending."""
        steps = 0
        while pending := self.store.pending():
            for event in pending:
                if steps >= max_steps:
                    raise RuntimeError(f"Stopped after {max_steps} steps, possible event loop")
                self._process(event)
                steps += 1
        return steps

    def _process(self, event: Event) -> None:
        handler = self.handlers.get(event.type)
        if handler is None:  # nothing reacts to this event type, e.g. a final outcome
            self.store.complete(event.id, [])
            return
        started = time.monotonic()
        try:
            emitted = handler(event)
        except Exception as e:
            self.store.fail(event.id, repr(e))
            self.on_step(f"{event.type} #{event.id} failed: {type(e).__name__}")
            return
        self.store.complete(event.id, emitted)
        produced = ", ".join(dict.fromkeys(e.type for e in emitted)) or "nothing to do"
        self.on_step(f"{event.type} #{event.id} -> {produced} ({time.monotonic() - started:.1f}s)")


def ingest_emails(source: EmailSource, store: EventStore) -> int:
    """Add an EmailReceived event per new email. Returns how many were new."""
    new = 0
    for email in source.fetch():
        payload = email.model_dump(mode="json")
        if store.append(EMAIL_RECEIVED, payload, dedupe_key=f"email:{email.message_id}"):
            new += 1
    return new


def ingest_chat(text: str, author: str, store: EventStore) -> Event:
    """Add a ChatMessageReceived event for news typed in by the team."""
    message = Email(
        message_id=f"chat-{uuid4()}",
        sender=author,
        subject="Chat message",
        sent_at=datetime.now(UTC),
        body=text,
        channel="chat",
    )
    return store.append(CHAT_MESSAGE_RECEIVED, message.model_dump(mode="json"))
