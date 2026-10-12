"""Runs pending events through their handlers until nothing is left to do."""

from collections.abc import Callable

from delay_ai.email_source import EmailSource
from delay_ai.events import EMAIL_RECEIVED, Emit, Event, EventStore

Handler = Callable[[Event], list[Emit]]


class Orchestrator:
    def __init__(self, store: EventStore, handlers: dict[str, Handler]):
        self.store = store
        self.handlers = handlers

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
        try:
            emitted = handler(event)
        except Exception as e:
            self.store.fail(event.id, repr(e))
            return
        self.store.complete(event.id, emitted)


def ingest_emails(source: EmailSource, store: EventStore) -> int:
    """Add an EmailReceived event per new email. Returns how many were new."""
    new = 0
    for email in source.fetch():
        payload = email.model_dump(mode="json")
        if store.append(EMAIL_RECEIVED, payload, dedupe_key=f"email:{email.message_id}"):
            new += 1
    return new
