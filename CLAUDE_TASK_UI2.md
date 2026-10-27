# Task: readability pass on the Prysma dashboard

You are working in `C:\Users\drift\Documents\watchtower-test-master` (Python +
FastAPI, no JS framework). The web UI is `prysma/web/` — `app.py` plus
`templates/index.html` and `templates/scan.html`, rendered by `.replace()` on
`{placeholder}` tokens (**never** `.format()`; the CSS and JS hold literal braces).

You have the `mobbin` MCP server available and authenticated. Use it for the
layout judgement calls.

The user is dyslexic. Every change below is about **readability and navigability**,
not new features. Prefer more whitespace, larger type, and clear separation over
density.

## 1. The watch list becomes a real list, with "Add new"

Today there are two fixed lists: *Interval timers* and *App blockers*. A user who
wants to track a different market (video games, say) cannot.

Replace the switcher with a list that has an explicit **"+ Add new"** entry:

- "+ Add new" asks for a **name** and creates a new, empty watch list with that
  name. It then becomes switchable exactly like the existing two.
- Lists are **user-named** and persist. Rename and delete must be possible (a
  small control per list, not a new page).
- Switching lists must keep scoping every tab's counts and tables to the selected
  list, as it does now.
- The two seeded lists keep working and keep their data.

Store this the smallest way that works. `competitors.watch_list` already holds the
list key; today the valid keys live in the `WATCH_LISTS` dict in
`prysma/storage/database.py`. Add a table (or equivalent) for user-created lists so
the set is no longer hard-coded, and migrate the two seeded lists into it. Keep the
existing `watch_list` values so no data moves.

Guard the name: trim it, reject empty, cap the length, and do not allow one that
collides with an existing list. Escape it wherever it is shown — it is user input.

## 2. Move "Find your market" above the summary

It currently sits below the KPI row, which reads as an afterthought. In the sketch
it sits directly under the watch list, **above** the summary.

Order the Overview tab as: **watch list → Find your market → Summary (KPI cards)
→ Actions → Competitor news search**.

"Find your market" stays — it is how a specific app gets added — but it should read
as the primary entry point rather than something to scroll past.

## 3. Insights: replace Severity with Type

"high" / "medium" / "low" means nothing to the user. Replace that column with
**Type**, using these four kinds:

| Type | Meaning |
|---|---|
| **Rating change** | a rating or rating-count move |
| **Listing change** | a description, title or metadata edit |
| **Negative review** | a review that names a complaint worth acting on |
| **Competitor news** | news about the competitor |

Rules:

- One column, one clear label per row. No severity anywhere in the UI.
- Where a type carries more information, say it in words the user can act on — a
  negative review should read as a complaint, not a score. Keep the "feature
  potential" idea: say plainly what a user is asking for.
- Keep the existing time column but label it clearly, and show it in the reader's
  own terms rather than a raw UTC stamp where practical.
- Add the action the sketch shows: from an insight you can **go to the full
  review** or the competitor it belongs to.

The data is already there — `alerts.severity`, `findings.finding_type`,
`aso_changes.change_type`. Map them onto the four types above; do not invent a new
detector. Where a row genuinely does not fit one of the four, pick the closest and
say so in the commit message.

## 4. Move ASO changes into the competitor cards

ASO changes currently sit in their own table, where they blur together. They belong
with the app they affect.

- Each competitor card lists **its own** changes underneath it, most recent first,
  with a clear label saying these are this app's changes.
- Drop the standalone "ASO changes" section from the Competitors tab.
- **Keep the "ASO changes (7d)" KPI card** as a count. It still opens the
  Competitors tab.
- If an app has no changes, say so quietly — do not leave a blank space.

## 5. Reformat the analysis output so it is actually readable

The strategic analysis and market-gap reports come back as Markdown and are
currently shown with the `**` intact, squeezed together. Example of what the user
sees and cannot read:

```
**Competitive Threats**
- **ASO velocity**: 8+ interval-timer apps updated descriptions and metadata in this cycle
- **Rating moats**: Tabata Timer (4.89), Box Timer (4.85) sustain >4.8 ratings
```

Render a **safe subset of Markdown** instead, so it reads like a rendered document:

- `**bold**` → real bold
- `#` / `##` / `###` headings → real headings, sized
- `-` / `*` / `1.` lists → real list items with proper indentation
- blank lines → real paragraph spacing
- generous line height and space between blocks

**This must not reintroduce injection.** The report text is model output derived
from scraped reviews. The escaping added recently stays: escape first, then apply
only the inline markup above to the escaped text, and never emit raw HTML from the
report. Write a test that proves a report containing `<script>`, `<img onerror>`
and a `{placeholder}` still renders inert.

Keep it dependency-free — no Markdown library, no CDN. A small, tested helper is
right.

## Hard constraints

- Pure HTML/CSS/vanilla JS. No React, no build step, no npm, no CDN.
- Templates use `.replace()` — introduce no `{}` syntax that conflicts.
- Every user-supplied or scraped value stays escaped.
- Do not edit `prysma/security.py`.
- Do not change an existing API route's contract. `/api/status` must keep working —
  the Docker healthcheck uses it. New routes are fine.
- Keep it fast on a 2 vCPU VPS.

## Verify before you finish

1. `python -m pytest tests/ -q` — must stay green (157 tests), and add tests for:
   user-created lists (create, rename, delete, name collision, scoping), the
   severity→type mapping, and the Markdown renderer's safety.
2. Run the app locally and confirm: a new list can be created from "+ Add new" and
   switches correctly; "Find your market" sits above the summary; the Insights
   table shows Type and no severity; a competitor card shows its own ASO changes;
   and a real report renders with bold, headings and list spacing.
3. Confirm no unescaped path was introduced.

Report what you changed and anything you could not do.
