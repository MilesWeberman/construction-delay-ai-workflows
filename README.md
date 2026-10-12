# Construction Delay AI Workflows

Pilot: reduce project delays caused by **late material deliveries**.

Delivery news (email, chat) → events → update affected schedule activities →
re-plan the schedule to minimise project delay → human review in a UI.

## Vision

The pilot starts with one problem, late deliveries. The real value is wider: this
tool becomes a **proactive, AI-enabled scheduling layer** that eventually replaces
a contractor's legacy scheduling systems. It is one place to store, view,
organise and optimise scheduling across every project.

Today's tools record the plan. This layer acts on it. When something changes, it
works out the effect on the programme, proposes ways to recover the time, and
orchestrates the follow-up with the people involved. Every change is
**optimised for reducing delay**.

It starts by connecting to the systems already in place and pulling from them:

- **Scheduling:** Primavera P6, Asta Powerproject, Microsoft Project
- **Email:** Outlook / Microsoft 365, Gmail
- **Procurement and ERP:** COINS, SAP, Viewpoint
- **Project and document platforms:** Procore, Autodesk Construction Cloud, Aconex
- **Spreadsheets:** Excel material and procurement trackers

Over time it becomes the contractor's own internal application. Planners and
site teams work in it directly, and the legacy tools become data sources rather
than the system of record.

## Setup

### 1. Get an Anthropic API key

1. Sign in to the [Claude Console](https://console.anthropic.com), using the
   company organisation if there is one so usage is billed to the project.
2. Under **Billing**, add credits or a payment method. API calls fail without them.
3. Under **API keys**, choose **Create key** (e.g. `delay-ai-pilot`) and copy it.
   It starts with `sk-ant-` and is shown only once.

### 2. Install and configure

```bash
uv sync
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=anthropic/claude-sonnet-5
```

`.env` is gitignored and loaded automatically by the CLI. Never commit it or
paste the key into chat or tickets.

To use another provider, set its key and any
[litellm model string](https://docs.litellm.ai/docs/providers), e.g.
`OPENAI_API_KEY=...` with `LLM_MODEL=openai/<model>`.

Gmail and Outlook credentials are not needed yet; they come with the email
connectors.

## Web app

React (Vite + TypeScript) in `web/`, over a small FastAPI API in
`src/delay_ai/api.py`. Build the UI once, then one command serves both:

```bash
cd web && npm install && npm run build && cd ..
uv run delay-ai serve        # http://localhost:8000
```

For UI development, run `uv run delay-ai serve` and `cd web && npm run dev`
(http://localhost:5173, which proxies `/api` to the server).

One page, like a scheduling app with AI built in: the completion date, AI
alerts (a late delivery with recovery options to choose; deliveries the AI
matched to tasks, to confirm), the schedule as a calendar, the inbox and
materials as tables (click an email to read it), and the outbox once an option
is chosen. The assistant is on the right.

The server keeps no state. Every visitor starts from the cached first run (see
below); what they do is saved as events in their own browser's localStorage and
sent with each request, so each device keeps its own demo. **Reset demo** starts
again from the cached run.

## Run (CLI)

```bash
rm -f data/local/events.db   # optional: start from a clean event log
uv run delay-ai ingest       # reads data/sample/emails into data/local/events.db
```

Prints the materials table built from the emails, the emails that need a person
to review them, and any failed events. Failed events (e.g. a missing API key)
are retried on the next run.

With the sample inbox you should see:

- **14 materials**, with the delays applied: steel `PO-24110` on 2027-01-12,
  lifts `PO-24160` on 2027-03-24, kitchens `PO-24170` on 2027-06-23
- **Links to confirm:** materials where the rules and the LLM chose different
  activities, or the rules found none (e.g. plasterboard: the rules say A06,
  the LLM should say A13)
- **Delays:** steel moves the finish +7 working days (to 2027-09-01); the lifts
  and kitchen delays are absorbed (kitchens only because steel already pushed
  fit-out back). Kitchens shows once its link is confirmed, if it needed confirming
- **Recovery options:** up to 3 options for the steel delay, each scored by the
  CPM against the whole current plan
- **Needs review:** the Clearview windows email (possible delay, no firm date)
- **Failed:** nothing

Each material is linked to the activity that needs it. The link is made
automatically when the rules and the LLM agree; otherwise a planner confirms it:

```bash
uv run delay-ai link PO-24150 A13
```

The chat takes four kinds of message. Delivery news (e.g. from a phone call)
goes through the same rules, LLM and checks as an email. Site news (weather,
labour, plant, access) is recorded as a task taking longer or not being able to
start before a date; its effect on completion is assessed and, if it slips,
recovery options are proposed, just like a late delivery. A suggested schedule
change is turned into edits, scored by the CPM, and can be chosen like a
recovery option. Questions are answered from the knowledge files and the plan:

```bash
uv run delay-ai chat "Pennine rang: steel PO-24110 now arriving 19/01/2027" --author "Priya Shah"
uv run delay-ai chat "Drylining gang is two men short for the next month"
uv run delay-ai chat "Can glazing start as soon as decking is under way?"
uv run delay-ai chat "Why is the kitchen delay not affecting the finish?"
```

When a delay pushes out the finish, the planner proposes recovery options. Pick
one, then read the drafted messages:

```bash
uv run delay-ai choose <event> <number>   # ids are printed by ingest
uv run delay-ai outbox
```

## Cached first run

The app starts from `data/sample/seed_events.json`: the events of one full run
of the sample inbox, so visitors don't wait for (or pay for) about 30 LLM calls.
Regenerate it after changing prompts, knowledge files or sample data:

```bash
uv run delay-ai seed
```

## Develop

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Knowledge

Expert context lives in Markdown files in `src/delay_ai/knowledge/`, and the
planner (and chatbot) read them on every call:

- `construction.md`: how UK buildings are built, terms, lead times, CDM 2015
- `scheduling.md`: critical path, float, and how delays are recovered
- `playbook.md`: the contractor's own rules; edit this with their planners

## Pilot simplifications

Shortcuts taken on purpose for v0. Each one is a candidate for after the pilot.

**Schedule**
- Read from a CSV export only, not P6, Asta or MS Project files.
- Finish-to-start dependencies only, with no lag.
- Mon–Fri working calendar with no bank holidays.
- No resource constraints (crews, cranes).
- Dates are computed from the project start; there's no progress or status date.
- An activity can start the working day after its material arrives.
- Each delay is assessed against the plan at that moment. It isn't re-assessed
  when later changes move the plan, or when a material is re-linked.

**Materials**
- One material per PO.
- Built from supplier emails; there is no materials spreadsheet.
- Each material is linked to one activity only.
- Linking rules only compare words in the material and activity names.

**Email**
- Read from a local `.eml` folder. There are no Gmail or Outlook connectors yet;
  the demo shows the sample inbox, which is hardcoded.
- Plain-text body only; attachments are ignored.
- A supplier is recognised by the domain of the sender's email address.
- PO numbers must look like `PO-<digits>`.
- Rules only read dates written in full with a year; the LLM resolves the rest.
- A fixed confidence threshold (0.7) decides what goes to review.
- If one item in an email fails a check, the whole email goes to review.
- Chat messages are trusted as coming from the team: they can update any
  supplier's order, but can't create new orders.
- The chat has no memory of earlier messages; each message stands alone.
- Site news from the chat is applied to the schedule straight away (no review),
  and only as "takes N more days" or "can't start before a date". Weather isn't
  read from a forecast service.

**Events**
- One SQLite file, and one CLI run at a time per database (a lock file refuses a
  second run).
- Event status (pending/done/failed) is updated in place, so the table isn't strictly append-only.
- Failed events are retried only when the CLI runs again; there's no backoff.

**Demo app**
- The first run is cached in `seed_events.json`; it isn't refreshed
  automatically when prompts or sample data change.
- Each visitor's changes live only in their browser (localStorage); they're
  lost if the browser storage is cleared, and they don't sync between devices.
- Visitors' chat and option choices call the LLM on the app's API key.
- The inbox is the hardcoded sample folder; emails in review can't be resolved
  in the app yet.
- The schedule is shown as a calendar only; there's no Gantt or critical-path view.
- The server trusts the events the browser sends back; fine for a demo, not for
  real users (that needs accounts and server-side storage).
- Choosing an option waits on the LLM for about a minute with no live progress.

**Knowledge**
- No RAG: every knowledge file goes into every prompt whole. Fine while the
  files are small; retrieval is needed once there are many documents.
- The knowledge is general UK practice, not yet the client's own standards.

**Recovery options**
- Three kinds of edit only: drop a dependency, shorten an activity (by up to
  30%), or ask for an earlier delivery.
- A phased delivery is modelled as the whole PO arriving earlier.
- Options are proposed only for delays that push out the finish.
- Options are scored when proposed. If the plan changes before one is chosen
  (e.g. a material gets linked), the list keeps the old scores; the action
  plan recalculates the finish when an option is chosen.
- One option can be chosen per delay.
- The knowledge files (`src/delay_ai/knowledge/`) guide the LLM but aren't enforced
  by the CPM. A planner still checks options, e.g. for safety-critical links.

**Actions**
- Emails and notifications are drafted to an outbox and never sent.
- Choosing an option updates the plan for dropped links and shortened
  activities. An earlier delivery only counts once the supplier confirms it by
  email.
- People are notified based on the activities in `contacts.csv`, and the
  project team (contacts with no activities) hears about every change.
- There's no undo for a chosen option yet.
