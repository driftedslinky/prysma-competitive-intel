# Task: let the Insights table be sorted by column

The Insights table is rendered in `prysma/web/templates/index.html` around line
430:

```html
<div class="table-wrap"><table>
  <thead><tr><th>Type</th><th>Competitor</th><th>What happened</th><th>When (your time)</th><th>Go to</th></tr></thead>
  <tbody>{findings_rows}</tbody>
</table></div>
```

The rows are built in `prysma/web/app.py` in the `findings_rows` loop near line
363, and the database orders them `ORDER BY f.importance DESC`.

The problem: with the current data, 16 "Negative review" rows (importance 5) and
21 listing rows (importance 3) sit above all 52 "Competitor news" rows
(importance 2). Somebody reading the tab sees only negative reviews and has to
scroll a long way to discover that other kinds of insight exist at all.

## What to build

Make the table sortable **client-side**, by clicking a column header. No backend
change, no new route, no change to the query.

1. Every `<th>` in that table becomes clickable. Clicking it sorts the existing
   `<tbody>` rows by that column, and clicking the same header again reverses
   the direction. This must be plain JavaScript in the existing `<script>` block
   in `index.html` — the rows are already in the DOM, so re-querying the server
   is not wanted.

2. Show which column is sorted and which way, using a small arrow in the header
   (`▲` / `▼`). Add `aria-sort="ascending|descending|none"` on the headers so it
   is not purely visual.

3. Sorting on **Type** should group all rows of the same type together. Sort on
   the visible badge text, so the groups run in a stable, predictable order.

4. The "When (your time)" column holds a timestamp. Sort it **chronologically**,
   not alphabetically — put the machine-readable value in a
   `data-sort="<ISO-8601>"` attribute on the `<td>` and sort on that, falling
   back to the cell text when the attribute is absent. Do the same trick for any
   column whose displayed text is not what you want to sort on.

5. The heading beside the table currently reads "Most important first" (line
   427). It should say what the table is actually showing: keep
   "Most important first" for the default order, and change it when the user
   sorts by something else — for example "Sorted by type".

6. The default order must stay exactly as it is now. The server still returns
   importance-first, and the table must not reorder itself on load.

## Accessibility and house style

- A clickable header must be reachable and usable from the keyboard: make it a
  real focusable control (`tabindex` plus Enter/Space handling, or a `<button>`
  inside the `<th>`), not a bare `<th onclick>`.
- The template already has a `spellcheck`-free escaped-output convention and a
  `_esc` / `esc()` helper. Do not introduce raw interpolation of scraped text.
- Match the existing dark-theme styling and the existing CSS variables. Add any
  new rule to the template's `<style>` block.

## Tests

Add tests in the existing style under `tests/`:

- the table renders one `data-sort` attribute per sortable cell that needs one
- the default row order is unchanged (the first row is still the most important)
- the header markup carries `aria-sort` and a focusable control

Client-side sorting itself is hard to assert without a browser; assert the
markup contract, and say so plainly in the test docstring rather than pretending
to test the interaction.

## Do not

- Do not change the database query, the KPI counts, or any other tab.
- Do not hide or collapse rows to make the list shorter.
- Do not touch `prysma/security.py`, the rate limiting, or the demo URL.
- Do not reformat unrelated code.

Current suite is **221 passing**. It must still pass. Report the final count.
