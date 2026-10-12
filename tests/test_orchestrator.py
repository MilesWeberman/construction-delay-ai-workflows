import pytest

from delay_ai.email_source import FolderEmailSource
from delay_ai.events import EMAIL_RECEIVED, Emit, EventStore
from delay_ai.orchestrator import Orchestrator, ingest_emails


def test_runs_chain_of_handlers_to_completion():
    store = EventStore()
    store.append("A", {})
    handlers = {"A": lambda e: [Emit("B", {})], "B": lambda e: [Emit("C", {})]}

    Orchestrator(store, handlers).run()

    assert [(e.type, e.status) for e in store.all()] == [
        ("A", "done"),
        ("B", "done"),
        ("C", "done"),
    ]


def test_failed_handler_does_not_stop_others():
    store = EventStore()
    store.append("Bad", {})
    store.append("Good", {})

    def boom(event):
        raise ValueError("bad input")

    Orchestrator(store, {"Bad": boom, "Good": lambda e: []}).run()

    bad, good = store.all()
    assert bad.status == "failed"
    assert "bad input" in bad.error
    assert good.status == "done"


def test_stops_runaway_loops():
    store = EventStore()
    store.append("Loop", {})
    with pytest.raises(RuntimeError, match="event loop"):
        Orchestrator(store, {"Loop": lambda e: [Emit("Loop", {})]}).run(max_steps=10)


def test_ingest_emails_skips_already_seen(sample_dir):
    store = EventStore()
    source = FolderEmailSource(sample_dir / "emails")

    assert ingest_emails(source, store) == 12
    assert ingest_emails(source, store) == 0
    assert all(e.type == EMAIL_RECEIVED for e in store.all())
