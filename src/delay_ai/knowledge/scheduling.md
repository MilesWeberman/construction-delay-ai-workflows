# Scheduling context

How programmes behave and how delays are recovered. It goes into the planner's
and the chatbot's prompts.

## Critical path
- The critical path is the longest chain of dependent activities; it sets the
  finish date. Activities on it have zero **total float**.
- Delaying a critical activity delays the finish by the same amount, unless
  something else is recovered.
- Delaying a non-critical activity uses its float first. Once the float is
  used, it becomes critical.
- Recovering time on one path can make another path critical. The real gain is
  limited by the next-longest path.

## How this tool models the programme
- Working days only (Monday to Friday). Dependencies are finish-to-start.
- A material constrains the activity that needs it: the activity can start the
  working day after delivery.
- All dates and days recovered are calculated by the CPM engine, never by the
  LLM.

## Site news
- Weather, labour, plant or access problems are recorded as either "takes N more
  working days" (the task is slowed while under way) or "can't start before a
  date" (the crew or a weather window isn't available yet).
- The effect on completion depends on float, like a late delivery.

## Recovery techniques
- **Resequencing / fast-tracking**: overlap activities that were planned in
  series, e.g. facade following the frame floor by floor. Modelled as dropping a
  dependency. Adds coordination and interface risk.
- **Crashing / acceleration**: add labour or shifts to shorten an activity.
  Modelled as shortening it, at most 30% for labour-driven work. Costs money and
  has diminishing returns.
- **Supply-side recovery**: ask the supplier for an earlier or phased delivery,
  or find an alternative supplier. Modelled as an earlier delivery date, and
  only counts once the supplier confirms it.
- Prefer options that recover time with the least cost and risk, and say what
  each one depends on.

## What a good recommendation includes
- Which activities change and why it helps the critical path.
- Who is affected: trades, subcontractors, suppliers.
- Rough cost and the main risks, including safety.
- What has to be true for it to work (e.g. supplier capacity, crane time).
