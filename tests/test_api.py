"""The web API, from the cached seed (no LLM calls)."""

from fastapi.testclient import TestClient

from delay_ai.api import app

client = TestClient(app)


def view(**body):
    response = client.post("/api/view", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_first_visit_shows_the_seeded_state():
    page = view()
    v = page["view"]
    assert page["events"] == []  # nothing of the visitor's own yet
    assert v["completion"] == {"date": "2027-09-01", "planned": "2027-08-23", "slip_days": 7}
    (alert,) = v["alerts"]
    assert alert["headline"].startswith("Structural steel")
    assert len(alert["recovery"]["options"]) == 3
    assert len(v["links"]) == 4
    assert len(v["inbox"]) == 12
    assert v["inbox"][0]["result"] == "Delivery confirmed"
    assert {e["kind"] for e in v["calendar"]} == {"activity", "delivery", "delivery_moved"}


def test_visitor_events_round_trip_through_the_browser():
    first = view()
    linked = view(
        seed=first["seed"],
        events=first["events"],
        action={"kind": "link", "links": [["PO-24170", "A16"]]},
    )
    assert len(linked["events"]) > 0
    assert len(linked["view"]["links"]) == 3

    # next visit: the browser sends its saved events back
    again = view(seed=linked["seed"], events=linked["events"])
    assert len(again["view"]["links"]) == 3
    assert any("itchen" in name for name in again["view"]["absorbed"])  # now assessed


def test_events_from_an_old_seed_are_dropped():
    first = view()
    linked = view(seed=first["seed"], action={"kind": "link", "links": [["PO-24170", "A16"]]})
    stale = view(seed="old-seed", events=linked["events"])
    assert len(stale["view"]["links"]) == 4


def test_choosing_twice_is_refused(monkeypatch):
    first = view()
    options_event = first["view"]["alerts"][0]["recovery"]["event"]
    monkeypatch.setattr("delay_ai.api.missing_api_key", lambda: None)
    monkeypatch.setattr("delay_ai.api.Orchestrator.run", lambda self: 0)
    chose = view(action={"kind": "choose", "options_event": options_event, "number": 1},
                 seed=first["seed"])  # fmt: skip
    response = client.post(
        "/api/view",
        json={
            "seed": chose["seed"],
            "events": chose["events"],
            "action": {"kind": "choose", "options_event": options_event, "number": 2},
        },
    )
    assert response.status_code == 400
