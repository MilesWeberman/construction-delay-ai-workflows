"""Streamlit demo app: `uv run streamlit run src/delay_ai/app.py`.

Every visitor starts from the cached sample run (seed_events.json), with no LLM
calls. What they do afterwards (confirm links, choose options, chat) becomes new
events, which are saved in their own browser's localStorage. So each device
keeps its own demo, and the shared seed never changes.
"""

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
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
st.set_page_config(page_title="Delay AI", page_icon="🏗️", layout="wide")


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
        st.caption("Loading your saved demo…")
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
    s = store()
    if kind == "link":
        emit = planner_link(*args)
        s.append(emit.type, emit.payload)
        label = f"Linking {args[0]} to {args[1]}"
    elif kind == "choose":
        emit = choose_option(s.get(args[0]), args[1])
        s.append(emit.type, emit.payload)
        label = "Drafting the action plan (about a minute)"
    else:  # chat
        ingest_chat(args[0], "You", s)
        label = "Thinking"
    needs_llm = kind != "link"
    if needs_llm and (key := missing_api_key()):
        st.error(f"{key} is not set, so the LLM can't run. Add it to .env and restart.")
        return
    with st.status(label, expanded=True) as status:
        Orchestrator(s, handlers(s, DATA), on_step=status.write).run()
        status.update(label="Done", state="complete", expanded=False)


# ---------- helpers ----------


def of_type(events: list[Event], *types: str) -> list[Event]:
    return [e for e in events if e.type in types]


def children(events: list[Event], parent: Event) -> list[Event]:
    return [e for e in events if e.caused_by == parent.id]


def last_working_day(start, early_finish: int):
    return add_working_days(start, max(early_finish - 1, 0))


# ---------- page ----------

run_queued()
events = store().all()
project = load_project(DATA / "project.json")
base = load_schedule(DATA / "schedule.csv")
activities = current_activities(base, events)
names = {a.id: a.name for a in activities}
materials = build_materials(events)
schedule = schedule_with_materials(activities, materials, project.start_date)
original = compute_schedule(base, project.start_date)

with st.sidebar:
    st.header("🏗️ Delay AI")
    st.caption(
        "Pilot: catch late material deliveries, see their effect on the programme, "
        "and choose how to recover."
    )
    st.write(f"**{project.name}**, {project.location}")
    st.divider()
    st.caption(
        "This demo starts from a cached run of the sample inbox. Your changes are "
        "saved in this browser only."
    )
    st.button("Reset demo", on_click=reset, width="stretch")
    if key := missing_api_key():
        st.warning(f"{key} is not set: choosing options and chat are disabled.")

slip = schedule.duration_days - original.duration_days
reviews = of_type(events, NEEDS_REVIEW)
links = pending_link_suggestions(events)
chosen_for = {e.payload.get("options_event") for e in of_type(events, OPTION_CHOSEN)}
open_options = [e for e in of_type(events, RECOVERY_OPTIONS_PROPOSED) if e.id not in chosen_for]

st.title(f"{project.name} programme")
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Expected completion",
    f"{schedule.finish_date:%d %b %Y}",
    f"{slip:+d} working days vs plan" if slip else "on plan",
    delta_color="inverse",
)
c2.metric("Decisions waiting", len(open_options))
c3.metric("Links to confirm", len(links))
c4.metric("Emails to review", len(reviews))

inbox, mats, sched, delays, outbox, chat = st.tabs(
    ["📥 Inbox", "📦 Materials", "📅 Schedule", "⚠️ Delays & options", "📤 Outbox", "💬 Chat"]
)

# ---------- inbox ----------

with inbox:
    left, right = st.columns([3, 1])
    left.caption("Sample supplier inbox (hardcoded for the demo), newest first.")
    with right:
        st.button("Connect Gmail", disabled=True, width="stretch")
        st.button("Connect Outlook", disabled=True, width="stretch")
        st.caption("Connectors come after the pilot.")
    received = {e.payload["message_id"]: e for e in of_type(events, EMAIL_RECEIVED)}
    for email in reversed(FolderEmailSource(DATA / "emails").fetch()):
        event = received.get(email.message_id)
        outcome = []
        for child in children(events, event) if event else []:
            p = child.payload
            if child.type == MATERIAL_ORDERED:
                m = p["material"]
                outcome.append(f":blue[Order {m['po_number']}, delivery {m['planned_delivery']}]")
            elif child.type == DELIVERY_DATE_CHANGED:
                outcome.append(
                    f":orange[Delivery moved: {p['po_number']} "
                    f"{p['old_delivery']} → {p['new_delivery']}]"
                )
            elif child.type == DELIVERY_CONFIRMED:
                outcome.append(f":green[Confirmed: {p['po_number']}]")
            elif child.type == NEEDS_REVIEW:
                outcome.append(":red[Needs review: " + "; ".join(p["problems"]) + "]")
            elif child.type == EMAIL_IGNORED:
                outcome.append(":gray[Ignored: not about orders or deliveries]")
        with st.container(border=True):
            st.markdown(
                f"**{email.subject}**  \n{email.sender} · {email.sent_at:%a %d %b %Y %H:%M}"
            )
            st.markdown("  \n".join(outcome) or ":gray[Not processed]")
            with st.expander("Show email"):
                st.text(email.body)

# ---------- materials ----------

with mats:
    st.subheader("Materials")
    st.caption("Built from the supplier emails; each row traces back to one.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "PO": m.po_number,
                    "Material": m.description,
                    "Supplier": m.supplier,
                    "Delivery": m.planned_delivery,
                    "Needed for": f"{m.activity_id} {names[m.activity_id]}"
                    if m.activity_id
                    else "Not linked yet",
                }
                for m in materials
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Links to confirm")
    if not links:
        st.caption("Nothing to confirm.")
    ids = [a.id for a in activities]
    for suggestion in links:
        p = suggestion.payload
        material = next(m for m in materials if m.po_number == p["po_number"])
        with st.container(border=True):
            st.markdown(
                f"**{p['po_number']}** {material.description}  \n"
                f"Rules suggest **{p['by_rules'] or 'nothing'}**, the LLM suggests "
                f"**{p['by_llm'] or 'nothing'}**: {p.get('rationale', '')}"
            )
            pick = p["by_llm"] or p["by_rules"] or ids[0]
            col1, col2 = st.columns([3, 1])
            chosen = col1.selectbox(
                "Activity",
                ids,
                index=ids.index(pick),
                format_func=lambda i: f"{i} {names[i]}",
                key=f"link-{p['po_number']}",
                label_visibility="collapsed",
            )
            col2.button(
                "Confirm",
                key=f"confirm-{p['po_number']}",
                on_click=queue,
                args=("link", p["po_number"], chosen),
                width="stretch",
            )

# ---------- schedule ----------

with sched:
    view = st.segmented_control("View", ["Gantt", "Calendar"], default="Gantt")
    st.caption(
        f"Critical activities in red. Expected completion {schedule.finish_date:%d %b %Y} "
        f"(plan: {original.finish_date:%d %b %Y})."
    )
    rows = []
    for a in activities:
        s = schedule.activities[a.id]
        start = schedule.start_of(a.id)
        end = last_working_day(project.start_date, s.early_finish) + timedelta(days=1)
        rows.append(
            {
                "Activity": f"{a.id} {a.name}",
                "Start": start,
                "End": max(end, start + timedelta(days=1)),
                "Status": "Critical" if s.is_critical else f"Float {s.total_float} days",
                "Critical": s.is_critical,
            }
        )
    if view == "Calendar":
        calendar_events = [
            {
                "title": r["Activity"],
                "start": r["Start"].isoformat(),
                "end": r["End"].isoformat(),
                "color": "#d62728" if r["Critical"] else "#1f77b4",
            }
            for r in rows
        ] + [
            {
                "title": f"🚚 {m.po_number} {m.description}",
                "start": m.planned_delivery.isoformat(),
                "allDay": True,
                "color": "#2ca02c",
            }
            for m in materials
        ]
        calendar(
            events=calendar_events,
            options={
                "initialView": "dayGridMonth",
                "initialDate": project.start_date.isoformat(),
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,listMonth",
                },
                "firstDay": 1,
            },
            key=f"calendar-{len(events)}",
        )
    else:
        df = pd.DataFrame(rows)
        fig = px.timeline(
            df,
            x_start="Start",
            x_end="End",
            y="Activity",
            color="Critical",
            color_discrete_map={True: "#d62728", False: "#1f77b4"},
            hover_data={"Status": True, "Critical": False},
        )
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(showlegend=False, height=620, margin={"l": 0, "r": 0, "t": 10, "b": 0})
        deliveries = [
            {"Activity": f"{m.activity_id} {names[m.activity_id]}", "Date": m.planned_delivery,
             "Delivery": f"{m.po_number} {m.description}"}
            for m in materials if m.activity_id
        ]  # fmt: skip
        if deliveries:
            dots = px.scatter(
                pd.DataFrame(deliveries), x="Date", y="Activity", hover_name="Delivery"
            )
            dots.update_traces(marker={"symbol": "diamond", "size": 10, "color": "#2ca02c"})
            fig.add_traces(dots.data)
        fig.add_vline(x=schedule.finish_date, line_dash="dash", line_color="#d62728")
        st.plotly_chart(fig, width="stretch")
        st.caption("◆ material deliveries · dashed line: expected completion")

# ---------- delays & options ----------

with delays:
    st.subheader("Delays")
    for e in of_type(events, DELAY_ASSESSED):
        p = e.payload
        effect = (
            f":red[Completion +{p['project_slip_days']} working days → {p['new_finish']}]"
            if p["project_slip_days"] > 0
            else ":green[Completion unchanged]"
        )
        with st.container(border=True):
            st.markdown(
                f"**{p['po_number']}** for {p['activity_id']} {names[p['activity_id']]}: "
                f"delivery {p['old_delivery']} → {p['new_delivery']}  \n"
                f"Float before: {p['float_before_days']} days · {effect}"
            )
    st.subheader("Recovery options")
    proposals = of_type(events, RECOVERY_OPTIONS_PROPOSED)
    if not proposals:
        st.caption("No decisions needed.")
    chosen = {e.payload["options_event"]: e for e in of_type(events, OPTION_CHOSEN)}
    for e in reversed(proposals):
        about = e.payload["po_number"] or "your suggestion in chat"
        st.markdown(f"#### For {about}")
        if e.id in chosen:
            st.success(f"Chosen: {chosen[e.id].payload['option']['title']}. See the Outbox.")
        for r in e.payload["rejected"]:
            st.caption(f"Rejected by the CPM: {r['title']} ({'; '.join(r['problems'])})")
        options = e.payload["options"]
        columns = st.columns(len(options)) if options else []
        for column, (n, o) in zip(columns, enumerate(options, start=1), strict=True):
            with column.container(border=True):
                st.markdown(f"**{o['title']}**")
                st.metric("Recovers", f"{o['recovered_days']} working days",
                          f"completion {o['new_finish']}", delta_color="off")  # fmt: skip
                st.markdown(f"**Cost:** {o['cost']}")
                st.markdown(o["rationale"])
                st.markdown(f"**Risks:** {o['risks']}")
                if e.id not in chosen:
                    st.button(
                        "Choose this option",
                        key=f"choose-{e.id}-{n}",
                        on_click=queue,
                        args=("choose", e.id, n),
                        type="primary",
                        width="stretch",
                    )

# ---------- outbox ----------

with outbox:
    st.info("Drafts only: nothing is sent in the pilot.")
    plans = of_type(events, ACTION_PLAN_DRAFTED)
    if not plans:
        st.caption("Choose a recovery option to draft messages to everyone affected.")
    for e in reversed(plans):
        st.markdown(f"#### {e.payload['title']}")
        for m in e.payload["messages"]:
            with st.expander(f"To {m['name']} ({m['role']}): {m['subject']}"):
                st.caption(m["to"])
                st.text(m["body"])

# ---------- chat ----------

with chat:
    st.caption(
        "Pass on delivery news (e.g. from a phone call), suggest a change to the "
        "programme, or ask a question."
    )
    replies = {e.payload["chat_event"]: e for e in of_type(events, CHAT_REPLIED)}
    for e in of_type(events, CHAT_MESSAGE_RECEIVED):
        st.chat_message("user").write(e.payload["body"])
        if e.id in replies:
            st.chat_message("assistant").write(replies[e.id].payload["text"])
    examples = [
        "Clearview rang: windows PO-24131 now arriving 10/03/2027",
        "Can curtain walling start floor by floor while decking continues?",
        "Why is the kitchen delay not affecting completion?",
    ]
    cols = st.columns(len(examples))
    for col, example in zip(cols, examples, strict=True):
        col.button(example, on_click=queue, args=("chat", example), width="stretch")
    st.chat_input(
        "Message", key="chat_text", on_submit=lambda: queue("chat", st.session_state.chat_text)
    )

save_to_browser()
