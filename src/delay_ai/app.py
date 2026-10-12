"""Streamlit demo app: `uv run streamlit run src/delay_ai/app.py`.

A scheduling app with AI built in: the schedule is the page, AI alerts sit on
top of it, and the AI assistant is in the sidebar.

Every visitor starts from the cached sample run (seed_events.json), with no LLM
calls. What they do afterwards becomes new events, saved in their own browser's
localStorage, so each device keeps its own demo and the shared seed never changes.
"""

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_calendar import calendar
from streamlit_js_eval import streamlit_js_eval

from delay_ai.actions import choose_option
from delay_ai.cpm import add_working_days, compute_schedule
from delay_ai.email_source import FolderEmailSource
from delay_ai.events import (
    ACTION_PLAN_DRAFTED,
    CHAT_MESSAGE_RECEIVED,
    CHAT_REPLIED,
    DELAY_ASSESSED,
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    EMAIL_IGNORED,
    EMAIL_RECEIVED,
    MATERIAL_ORDERED,
    NEEDS_REVIEW,
    OPTION_CHOSEN,
    RECOVERY_OPTIONS_PROPOSED,
    Event,
    EventStore,
)
from delay_ai.impact import schedule_with_materials
from delay_ai.linking import planner_link
from delay_ai.llm import missing_api_key
from delay_ai.loaders import load_project, load_schedule
from delay_ai.materials import build_materials, pending_link_suggestions
from delay_ai.orchestrator import Orchestrator, ingest_chat
from delay_ai.plan import current_activities
from delay_ai.workflow import handlers

DATA = Path(__file__).resolve().parents[2] / "data" / "sample"
SEED = DATA / "seed_events.json"
STORAGE_KEY = "delay-ai-demo"
# Set in tests: there is no browser to read localStorage from.
NO_BROWSER = bool(os.environ.get("DELAY_AI_NO_BROWSER_STORAGE"))

load_dotenv()
st.set_page_config(page_title="Schedule", page_icon="🏗️", layout="wide")


# ---------- state: seed + this browser's own events ----------


@st.cache_data
def seed() -> tuple[list[dict], str]:
    text = SEED.read_text()
    return json.loads(text), hashlib.sha256(text.encode()).hexdigest()[:12]


def visitor_events(seed_hash: str) -> list[dict]:
    """This browser's saved events, if they were made on the same seed."""
    if NO_BROWSER:
        return []
    raw = streamlit_js_eval(
        js_expressions=f"localStorage.getItem('{STORAGE_KEY}') || ''", key="load"
    )
    if raw is None:  # the browser hasn't answered yet; Streamlit reruns when it does
        st.caption("Loading…")
        st.stop()
    saved = json.loads(raw) if raw else {}
    return saved.get("events", []) if saved.get("seed") == seed_hash else []


def store() -> EventStore:
    if "store" not in st.session_state:
        events, seed_hash = seed()
        s = EventStore()
        s.load(events)
        s.load(visitor_events(seed_hash))
        st.session_state.store = s
        st.session_state.seed_last_id = max(e["id"] for e in events)
    return st.session_state.store


def save_to_browser() -> None:
    """Write this visitor's events (everything after the seed) to localStorage."""
    if NO_BROWSER:
        return
    _, seed_hash = seed()
    events = store().export(after_id=st.session_state.seed_last_id)
    payload = json.dumps({"seed": seed_hash, "events": events})
    version = hashlib.sha256(payload.encode()).hexdigest()[:12]
    script = f"localStorage.setItem({json.dumps(STORAGE_KEY)}, {json.dumps(payload)})"
    streamlit_js_eval(js_expressions=script, key=f"save-{version}")


def reset() -> None:
    events, _ = seed()
    s = EventStore()
    s.load(events)
    st.session_state.store = s


# ---------- actions: queued by buttons, run at the top of the next rerun ----------


def queue(*action) -> None:
    st.session_state.todo = action


def run_queued() -> None:
    action = st.session_state.pop("todo", None)
    if action is None:
        return
    kind, *args = action
    if kind != "link" and (key := missing_api_key()):
        st.error(f"{key} is not set, so the AI can't run. Add it to .env and restart.")
        return
    s = store()
    if kind == "chat":
        ingest_chat(args[0], "You", s)
        label = "Thinking"
    else:
        if kind == "link":
            emit = planner_link(*args)
            label = "Updating the schedule"
        else:
            emit = choose_option(s.get(args[0]), args[1])
            label = "Updating the schedule and drafting messages (about a minute)"
        s.append(emit.type, emit.payload)
    with st.status(label) as status:
        Orchestrator(s, handlers(s, DATA), on_step=status.write).run()
        status.update(label="Done", state="complete")


def of_type(events: list[Event], *types: str) -> list[Event]:
    return [e for e in events if e.type in types]


def clicked_row(table_key: str) -> int | None:
    rows = st.session_state.get(table_key, {}).get("selection", {}).get("rows", [])
    return rows[0] if rows else None


def short(d: str | date) -> str:
    return f"{date.fromisoformat(str(d)):%d %b}"


# ---------- data ----------

run_queued()
events = store().all()
project = load_project(DATA / "project.json")
base = load_schedule(DATA / "schedule.csv")
activities = current_activities(base, events)
names = {a.id: a.name for a in activities}
materials = build_materials(events)
by_po = {m.po_number: m for m in materials}
schedule = schedule_with_materials(activities, materials, project.start_date)
original = compute_schedule(base, project.start_date)
delays = of_type(events, DELAY_ASSESSED)
proposals = of_type(events, RECOVERY_OPTIONS_PROPOSED)
chosen = {e.payload["options_event"]: e for e in of_type(events, OPTION_CHOSEN)}

# ---------- sidebar: AI assistant ----------

with st.sidebar:
    st.subheader("✨ AI assistant")
    st.caption("Tell it about a delivery, try a change, or ask a question.")
    replies = {e.payload["chat_event"]: e for e in of_type(events, CHAT_REPLIED)}
    with st.container(height=480, border=False):
        for e in of_type(events, CHAT_MESSAGE_RECEIVED):
            st.chat_message("user").write(e.payload["body"])
            if e.id in replies:
                st.chat_message("assistant").write(replies[e.id].payload["text"])
    st.chat_input(
        "Message", key="chat_text", on_submit=lambda: queue("chat", st.session_state.chat_text)
    )
    st.button("Reset demo", on_click=reset, type="tertiary")

# ---------- header ----------

slip = schedule.duration_days - original.duration_days
st.title(f"{project.name} schedule")
status = f":red[{slip:+d} working days late]" if slip > 0 else ":green[on plan]"
st.markdown(f"{project.location} · Completion **{schedule.finish_date:%d %b %Y}** · {status}")

# ---------- AI alerts ----------


def recovery_options(proposal: Event) -> None:
    if proposal.id in chosen:
        title = chosen[proposal.id].payload["option"]["title"]
        st.success(f"Chosen: {title}. Messages to everyone affected are in the Outbox.")
        return
    options = proposal.payload["options"]
    with st.expander(f"✨ {len(options)} ways to recover, suggested by AI and checked"):
        for n, o in enumerate(options, start=1):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.markdown(
                f"**{o['title']}**  \nWins back {o['recovered_days']} working days · {o['cost']}"
            )
            right.button("Choose", key=f"choose-{proposal.id}-{n}", on_click=queue,
                         args=("choose", proposal.id, n))  # fmt: skip
            with left.popover("Why"):
                st.write(o["rationale"])
                st.write(f"**Risks:** {o['risks']}")


absorbed = []
for delay in delays:
    p = delay.payload
    description = by_po[p["po_number"]].description
    material = description[:1].upper() + description[1:]
    if p["project_slip_days"] <= 0:
        absorbed.append(material)
        continue
    with st.container(border=True):
        st.markdown(
            f"⚠️ **{material}** now arrives {short(p['new_delivery'])} instead of "
            f"{short(p['old_delivery'])}. Completion moves {p['project_slip_days']} "
            "working days later."
        )
        for proposal in proposals:
            if proposal.payload.get("assessment_event") == delay.id:
                recovery_options(proposal)

for proposal in proposals:
    if proposal.payload["po_number"] is None:  # a change suggested in the chat
        with st.container(border=True):
            st.markdown("💡 **Your suggested change**")
            recovery_options(proposal)

links = pending_link_suggestions(events)
if links:
    ids = [a.id for a in activities]
    with st.container(border=True):
        with st.expander(f"🔗 {len(links)} new materials to place on the schedule"):
            for suggestion in links:
                p = suggestion.payload
                pick = p["by_llm"] or p["by_rules"] or ids[0]
                left, middle, right = st.columns([2, 2, 1], vertical_alignment="center")
                left.markdown(f"**{by_po[p['po_number']].description}** is needed for")
                activity = middle.selectbox(
                    "Activity",
                    ids,
                    index=ids.index(pick),
                    format_func=lambda i: names[i],
                    key=f"link-{p['po_number']}",
                    label_visibility="collapsed",
                )
                right.button("Confirm", key=f"confirm-{p['po_number']}", on_click=queue,
                             args=("link", p["po_number"], activity))  # fmt: skip

if absorbed:
    st.caption(f"Also delayed, with no effect on completion: {', '.join(absorbed)}.")

# ---------- schedule ----------

moved = {e.payload["po_number"] for e in of_type(events, DELIVERY_DATE_CHANGED)}
calendar_events = []
for a in activities:
    s = schedule.activities[a.id]
    start = schedule.start_of(a.id)
    end = add_working_days(project.start_date, max(s.early_finish - 1, 0)) + timedelta(days=1)
    calendar_events.append(
        {"title": a.name, "start": start.isoformat(), "end": max(end, start).isoformat()}
    )
for m in materials:
    late = m.po_number in moved
    calendar_events.append(
        {
            "title": f"{'⚠️' if late else '🚚'} {m.description}",
            "start": m.planned_delivery.isoformat(),
            "allDay": True,
            "color": "#ef6c00" if late else "#2e7d32",
        }
    )
first_problem = next((d for d in delays if d.payload["project_slip_days"] > 0), None)
opens_on = (
    date.fromisoformat(first_problem.payload["new_delivery"])
    if first_problem
    else project.start_date
)
calendar(
    events=calendar_events,
    options={
        "initialView": "dayGridMonth",
        "initialDate": opens_on.isoformat(),
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,listMonth",
        },
        "firstDay": 1,
        "height": 640,
    },
    key=f"calendar-{len(events)}",
)
st.caption("🚚 delivery · ⚠️ delivery moved")

# ---------- inbox ----------

st.subheader("Inbox")
received = {e.payload["message_id"]: e for e in of_type(events, EMAIL_RECEIVED)}


def result(email_event: Event | None) -> str:
    found = [e for e in events if email_event and e.caused_by == email_event.id]
    for e in found:
        if e.type == DELIVERY_DATE_CHANGED:
            return f"Delivery moved to {short(e.payload['new_delivery'])}"
        if e.type == NEEDS_REVIEW:
            return "Needs your review"
        if e.type == DELIVERY_CONFIRMED:
            return "Delivery confirmed"
        if e.type == EMAIL_IGNORED:
            return "Not relevant"
    orders = of_type(found, MATERIAL_ORDERED)
    return f"Order recorded ({len(orders)})" if orders else ""


emails = list(reversed(FolderEmailSource(DATA / "emails").fetch()))
st.dataframe(
    pd.DataFrame(
        [
            {
                "Date": f"{e.sent_at:%d %b}",
                "From": e.sender.split("@")[-1],
                "Subject": e.subject,
                "AI read it as": result(received.get(e.message_id)),
            }
            for e in emails
        ]
    ),
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="inbox",
)
if (row := clicked_row("inbox")) is not None:
    email = emails[row]
    review = [
        e for e in of_type(events, NEEDS_REVIEW) if e.payload["source_email"] == email.message_id
    ]
    with st.container(border=True):
        st.markdown(f"**{email.subject}**  \n{email.sender} · {email.sent_at:%d %b %Y %H:%M}")
        if review:
            st.warning("; ".join(review[0].payload["problems"]))
        st.text(email.body)
else:
    st.caption("Click an email to read it. The inbox is a fixed sample for the demo.")

# ---------- materials ----------

st.subheader("Materials")
st.dataframe(
    pd.DataFrame(
        [
            {
                "Material": m.description,
                "Supplier": m.supplier,
                "Delivery": f"{m.planned_delivery:%d %b %Y}",
                "Needed for": names[m.activity_id] if m.activity_id else "To place",
                "PO": m.po_number,
            }
            for m in materials
        ]
    ),
    hide_index=True,
)

# ---------- outbox ----------

messages = [
    m for e in reversed(of_type(events, ACTION_PLAN_DRAFTED)) for m in e.payload["messages"]
]
if messages:
    st.subheader("Outbox")
    st.caption("Drafts written by AI. Nothing is sent in the pilot.")
    st.dataframe(
        pd.DataFrame(
            [{"To": m["name"], "Role": m["role"], "Subject": m["subject"]} for m in messages]
        ),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="outbox",
    )
    if (row := clicked_row("outbox")) is not None:
        with st.container(border=True):
            st.caption(f"To {messages[row]['to']}")
            st.text(messages[row]["body"])

save_to_browser()
