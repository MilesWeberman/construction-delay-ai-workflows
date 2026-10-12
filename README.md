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

## Run

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

News that doesn't arrive by email, e.g. a phone call, can be typed in. It
goes through the same rules, LLM and checks as an email:

```bash
uv run delay-ai chat "Pennine rang: steel PO-24110 now arriving 19/01/2027" --author "Priya Shah"
```

When a delay pushes out the finish, the planner proposes recovery options. Pick
one, then read the drafted messages:

```bash
uv run delay-ai choose <event> <number>   # ids are printed by ingest
uv run delay-ai outbox
```

## Develop

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

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
- Read from a local `.eml` folder. Gmail and Outlook come later.
- Plain-text body only; attachments are ignored.
- A supplier is recognised by the domain of the sender's email address.
- PO numbers must look like `PO-<digits>`.
- Rules only read dates written in full with a year; the LLM resolves the rest.
- A fixed confidence threshold (0.7) decides what goes to review.
- If one item in an email fails a check, the whole email goes to review.
- Chat messages are trusted as coming from the team: they can update any
  supplier's order, but can't create new orders.

**Events**
- One SQLite file and a single process.
- Event status (pending/done/failed) is updated in place, so the table isn't strictly append-only.
- Failed events are retried only when the CLI runs again; there's no backoff.

**Recovery options**
- Three kinds of edit only: drop a dependency, shorten an activity (by up to
  30%), or ask for an earlier delivery.
- A phased delivery is modelled as the whole PO arriving earlier.
- Options are proposed only for delays that push out the finish.
- The playbook (`src/delay_ai/playbook.md`) guides the LLM but isn't enforced
  by the CPM. A planner still checks options, e.g. for safety-critical links.

**Actions**
- Emails and notifications are drafted to an outbox and never sent.
- Choosing an option updates the plan for dropped links and shortened
  activities. An earlier delivery only counts once the supplier confirms it by
  email.
- People are notified based on the activities in `contacts.csv`, and the
  project team (contacts with no activities) hears about every change.
- There's no undo for a chosen option yet.
