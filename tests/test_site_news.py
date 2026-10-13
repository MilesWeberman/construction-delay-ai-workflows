from datetime import date

import pytest
from test_chat_intents import send, setup  # noqa: F401  (pytest fixture)
from test_planner import edit, fake_propose

from delay_ai.chat import SiteNews
from delay_ai.events import (
    ACTIVITY_DISRUPTED,
    DISRUPTION_ASSESSED,
    RECOVERY_OPTIONS_PROPOSED,
)
from delay_ai.impact import make_disruption_handler, schedule_with_materials
from delay_ai.models import Activity
from delay_ai.plan import apply_edits
from delay_ai.planner import make_planner_handler

START = date(2026, 11, 2)
TODAY = date(2026, 10, 12)


def test_lengthen_and_not_before_edits():
    a = Activity(id="A", name="A", trade="t", duration_days=10)
    edits = [
        edit("lengthen", activity_id="A", days=5),
        edit("not_before", activity_id="A", not_before=date(2026, 11, 16)),
    ]
    (changed,), _, problems = apply_edits(edits, [a], [], TODAY)
    assert problems == []
    assert changed.duration_days == 15
    schedule = schedule_with_materials([changed], [], START)
    assert schedule.start_of("A") == date(2026, 11, 16)


@pytest.mark.parametrize(
    "bad",
    [
        edit("lengthen", activity_id="A", days=0),
        edit("lengthen", activity_id="A", days=100),
        edit("not_before", activity_id="A", not_before=date(2026, 1, 1)),
        edit("lengthen", activity_id="Z", days=2),
    ],
)
def test_invalid_site_edits(bad):
    a = Activity(id="A", name="A", trade="t", duration_days=10)
    assert apply_edits([bad], [a], [], TODAY)[2]


def with_site_handlers(setup):  # noqa: F811
    store, activities, handlers = setup
    planner = make_planner_handler(store, activities, START, fake_propose)
    return (
        store,
        activities,
        handlers
        | {
            ACTIVITY_DISRUPTED: make_disruption_handler(store, activities, START),
            DISRUPTION_ASSESSED: planner,
        },
    )


def test_labour_shortage_on_critical_task_slips_completion_and_gets_options(setup):  # noqa: F811
    news = SiteNews(
        edits=[edit("lengthen", activity_id="A13", days=5)],
        reason="drylining gang two men short",
        explanation="",
        confidence=0.9,
    )
    new, text = send(
        with_site_handlers(setup),
        "Drylining gang is two men short",
        "site_news",
        extract_site_news=lambda t, p, d: news,
    )

    assert text == (
        "Got it. I've added 5 working days to drylining and partitions. That pushes "
        "completion 5 working days later, to 8 Sep. I've suggested ways to recover on the "
        "schedule."
    )
    (assessed,) = [e for e in new if e.type == DISRUPTION_ASSESSED]
    assert assessed.payload["project_slip_days"] == 5
    (proposal,) = [e for e in new if e.type == RECOVERY_OPTIONS_PROPOSED]
    assert proposal.payload["assessment_event"] == assessed.id
    assert proposal.payload["po_number"] is None


def test_weather_on_task_with_float_does_not_move_completion(setup):  # noqa: F811
    news = SiteNews(
        edits=[edit("lengthen", activity_id="A18", days=3)],
        reason="heavy rain",
        explanation="",
        confidence=0.9,
    )
    new, _ = send(with_site_handlers(setup), "Rain stopped landscaping for 3 days",
                  "site_news", extract_site_news=lambda t, p, d: news)  # fmt: skip
    (assessed,) = [e for e in new if e.type == DISRUPTION_ASSESSED]
    assert assessed.payload["project_slip_days"] == 0
    assert not [e for e in new if e.type == RECOVERY_OPTIONS_PROPOSED]


def test_unclear_site_news_is_not_recorded(setup):  # noqa: F811
    news = SiteNews(
        edits=[edit("lengthen", activity_id="A99", days=2)],
        reason="?",
        explanation="",
        confidence=0.4,
    )
    new, text = send(with_site_handlers(setup), "Something happened", "site_news",
                     extract_site_news=lambda t, p, d: news)  # fmt: skip
    assert text.startswith("I'm not sure which work that affects")
    assert not [e for e in new if e.type == ACTIVITY_DISRUPTED]


def test_news_that_affects_no_task_gets_a_plain_answer(setup):  # noqa: F811
    news = SiteNews(
        edits=[],
        explanation="No crane lifts are planned between 15 and 19 Oct; steel starts in January.",
        reason="storm",
        confidence=0.9,
    )
    new, text = send(with_site_handlers(setup), "Storm Thursday to Monday, no crane lifts",
                     "site_news", extract_site_news=lambda t, p, d: news)  # fmt: skip
    assert text == "No crane lifts are planned between 15 and 19 Oct; steel starts in January."
    assert not [e for e in new if e.type == ACTIVITY_DISRUPTED]
