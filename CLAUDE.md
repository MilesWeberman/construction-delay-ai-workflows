# CLAUDE.md

Pilot for a UK construction contractor: reduce project delays caused by late
material deliveries. Read `README.md` for setup, the vision and the list of
pilot simplifications.

## Commands

```bash
uv sync                          # install
uv run pytest                    # tests (no API key needed: LLMs are faked)
uv run ruff check . && uv run ruff format .
uv run delay-ai ingest           # sample inbox -> data/local/events.db (real LLM, ~1.5 min)
uv run delay-ai chat "<text>"    # delivery news, a suggested change, or a question
uv run delay-ai link <PO> <activity> | choose <event> <n> | outbox
uv run delay-ai serve            # web app on :8000 (build first: cd web && npm run build)
cd web && npm run dev            # UI dev server on :5173, proxies /api to :8000
```

`ANTHROPIC_API_KEY` goes in `.env` (gitignored). Default model
`anthropic/claude-sonnet-5` via litellm, overridable with `LLM_MODEL`.

## How it works

Everything is an event in one SQLite table (`events.py`). Handlers are plain
functions `Event -> list[Emit]`, run by `orchestrator.py` until nothing is
pending. Each event records `caused_by`, so any result traces back to an email.

```
EmailReceived / ChatMessageReceived -> ingestion.py / chat.py
  -> MaterialOrdered -> linking.py -> MaterialLinked | LinkSuggested
  -> DeliveryDateChanged -> impact.py -> DelayAssessed
  -> planner.py -> RecoveryOptionsProposed -> (planner chooses) OptionChosen
  -> actions.py -> ActionPlanDrafted (outbox; nothing is sent)
```

State is rebuilt from events, never stored separately: `materials.py`
(materials table) and `plan.py` (schedule plus chosen options).

The web app: `view.py` turns events into page data, `api.py` (FastAPI, stateless)
replays the cached seed plus the browser's own events on each request, and
`web/` is the React UI. The browser keeps its events in localStorage.

## Design rules

- **Rules first, LLM for the gaps, then checks.** The LLM is never the only
  source of a fact: regex/rules cross-check extraction, rules and LLM must agree
  to auto-link, anything doubtful becomes `NeedsReview` or `LinkSuggested`.
- **The CPM computes every date and day count** (`cpm.py`). The LLM proposes
  edits and writes words; it never states numbers. Drafted messages get dates
  only from the appended "Key facts" block.
- **A person decides**: links that don't agree, recovery options, and sending.
- Domain knowledge for prompts lives in `src/delay_ai/knowledge/*.md`, loaded
  whole (no RAG).
- Keep it simple and readable; it's a pilot. Prefer the standard library.

## Working conventions

- Atomic PRs with short descriptions, stacked: branch `pr/NN-<slug>` from the
  previous PR branch and open it with `--base` on that branch. Body starts with
  "Stacked on #N."
- Any deliberate shortcut goes into README "Pilot simplifications" in the same PR.
- After UI changes run `cd web && npm run build` (type checks) and look at the page.
- Tests never call a real LLM: use `tests/fakes.py` (canned answers for the
  sample inbox) or pass a fake function into the handler factory.
- `data/sample/README.md` lists the expected outcome for each sample email; keep
  tests and that table in sync.
- Verify prompt changes against the real model on a scratch database
  (`--db <scratch path>`), not the user's `data/local/events.db`.
- Only one CLI run per database at a time (a lock file enforces it).
