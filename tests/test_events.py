from delay_ai.events import Emit, EventStore


def test_append_and_get():
    store = EventStore()
    event = store.append("Thing", {"x": 1})
    assert store.get(event.id).payload == {"x": 1}
    assert event.status == "pending"


def test_dedupe_key_ignores_duplicates():
    store = EventStore()
    assert store.append("Thing", {}, dedupe_key="k") is not None
    assert store.append("Thing", {}, dedupe_key="k") is None
    assert len(store.all()) == 1


def test_complete_marks_done_and_records_cause():
    store = EventStore()
    parent = store.append("Parent", {})
    store.complete(parent.id, [Emit("Child", {"n": 1})])
    child = store.pending()[0]
    assert store.get(parent.id).status == "done"
    assert child.type == "Child"
    assert child.caused_by == parent.id


def test_store_persists_to_file(tmp_path):
    path = tmp_path / "events.db"
    EventStore(path).append("Thing", {})
    assert len(EventStore(path).all()) == 1


def test_retry_failed_puts_events_back_to_pending():
    store = EventStore()
    event = store.append("Thing", {})
    store.fail(event.id, "boom")

    assert store.retry_failed() == 1
    assert store.get(event.id).status == "pending"
    assert store.get(event.id).error is None
