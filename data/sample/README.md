# Sample data: Riverside Court (fictional)

A 6-storey residential block in Leeds, starting 2 Nov 2026. All companies and
email addresses are made up (`*.example`).

| File | What it is |
|---|---|
| `project.json` | Project name, location, start date |
| `schedule.csv` | 20 activities, durations in working days, `;`-separated predecessors |
| `contacts.csv` | People to notify, with the activities they care about |
| `emails/` | A supplier inbox, oldest first |

There is no materials spreadsheet. The materials table (PO, supplier, planned
delivery, the activity that needs it) is **built from the inbox**: deterministic
parsing first (headers, known supplier domains, PO numbers, dates), the LLM only
for what rules can't get, then validation and human review of low-confidence rows.

## Order confirmations (build the materials table)

| Email | POs | Notes |
|---|---|---|
| `2026-08-24_order_northgate` | 7 POs | One email, one line per PO |
| `2026-08-27_order_steel` | PO-24110 steel, PO-24111 decking | Prose |
| `2026-09-01_order_glazing` | PO-24130 curtain wall, PO-24131 windows | One date for both |
| `2026-09-03_order_me` | PO-24140 M&E first fix | |
| `2026-09-08_order_lifts` | PO-24160 lifts | |
| `2026-09-10_order_kitchens` | PO-24170 kitchens | Relative date ("16 June next year") |
| `2026-09-15_newsletter` | none | Not relevant, ignore |

## Updates (trigger the workflow)

| Email | Material | Expected outcome |
|---|---|---|
| `2026-10-12_steel_delay` | Steel (A05, critical) | Delivery +10 working days, end date +7 (lead time absorbs 3) |
| `2026-10-12_lift_delay` | Lifts (A14, 85 days float) | Delivery +15 working days, absorbed by float. End date unchanged |
| `2026-10-12_kitchen_delay` | Kitchens (A16, critical) | Delivery +5 working days, end date +3. No PO number, so match on supplier |
| `2026-10-13_windows_maybe` | Windows (A10, 15 days float) | No date given, so it goes to a person for review |
| `2026-10-13_plasterboard_confirmed` | Plasterboard | Confirmed on time, so no change |

An activity can start the working day after its material arrives.
