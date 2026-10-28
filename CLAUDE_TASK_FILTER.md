# Task: a type filter above the two tables on the Insights tab

## The problem, in the user's words

> It's just stacked. It's negative review and then you keep scrolling and then it's
> the ASO changes and then you keep scrolling and then it's the different one. The
> user should be able to pick which one he wants to see at the top of the list.

The tables are ordered by importance, so every row of one kind comes first and the
other kinds are below the fold. Reading the tab, you see negative reviews and
nothing else. There is currently no control of any kind on the Type column.

A previous change made the columns **sortable**, which groups the types but still
leaves them stacked. That is not what was asked for. Keep the sorting — it does no
harm — but this task is about being able to **choose a type**.

## What to build

Add a **filter bar** above each of the two tables on the Insights tab:

1. The **Alerts** table — `prysma/web/templates/index.html`, around line 425. It
   currently has plain headers and a `{alert_rows}` body. Its section is
   `<section aria-labelledby="h-alerts">`.
2. The **Findings** table — `id="findings-table"`, body `{findings_rows}`.

Each bar is a row of buttons:

```
All (22)   |   Negative review (18)   |   Rating (3)   |   Listing (1)
```

- **"All"** is selected on load and shows every row, exactly as now. Nothing about
  the initial render may change.
- One button per type **present in that table's rows**. Do not render a button for
  a type with no rows — the Alerts and Findings tables may have different sets.
- Each button carries the count of rows of that type, and the count must equal the
  number of rows it will show. Derive both from the same source so they cannot
  disagree — this project has already had a bug where a KPI count and the rows it
  labelled disagreed, and it was caught on camera.
- Clicking a button shows only that type and hides the others. Clicking "All"
  restores every row.
- Filtering is **client-side** on rows already in the DOM. No new route, no query
  change, no page reload.

## How to get the type onto the row

The server already computes the type with `insight_type()` in
`prysma/web/app.py` and renders a badge for it in the `alert_rows` and
`findings_rows` loops. Do not duplicate that logic in JavaScript.

Put the machine-readable type on the row itself — for example
`<tr data-type="review">` — from the same value that builds the badge, so the
filter and the badge can never drift apart. Use the four canonical type keys:
`rating`, `listing`, `review`, `news`.

## Requirements

- **Accessibility.** The buttons are real `<button>` elements. The selected one
  carries `aria-pressed="true"`. Add `aria-label` text that says what the button
  does, not just the label. The hidden rows must be hidden from assistive
  technology too, not merely invisible — use the `hidden` attribute or a class
  that sets `display: none`, not `visibility: hidden` alone.
- **The count must be honest.** If a user dismisses an alert, the row count
  changes; the chip count should reflect the rows actually in the table at render
  time. Do not hard-code counts.
- **Visual consistency.** Match the existing dark theme. Reuse the existing
  `--accent`, `--muted`, `--surface-2` and `--border` variables and the existing
  pill/chip styling already in the template (there are badge rules near line 202
  and a watch-list chip style you can follow). Selected state must be obvious at
  a glance without relying on colour alone.
- **Empty state.** If a filter would show nothing, that cannot happen because the
  buttons are derived from the rows — but if every row is filtered out some other
  way, the table must not look broken.

## Tests

Add tests in the existing style under `tests/`:

- every row in both tables carries a `data-type` matching its badge
- a filter button is rendered for each type present, and not for a type with no rows
- the count in each button equals the number of rows with that `data-type`
- "All" carries `aria-pressed="true"` on load, and is the only one that does
- the default render is unchanged: every row is present and none is hidden

The click itself is JavaScript; assert the markup contract and say so in the
docstring rather than pretending to test the interaction.

## Do not

- Do not change the database query, the KPI counts, or the other tabs.
- Do not remove or break the existing column sorting.
- Do not hide rows by default, and do not shorten the lists by filtering at the
  server.
- Do not touch `prysma/security.py`, the rate limiting, or the demo URL.
- Do not reformat unrelated code.

Current suite is **225 passing**. It must still pass. Report the final count.
