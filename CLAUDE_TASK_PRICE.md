# Task: show price on competitor cards, and fix a hardcoded placeholder

Two things. Both are small and self-contained.

## 1. The discovery search placeholder is hardcoded to one market

`prysma/web/templates/index.html` line 329:

```html
<input type="text" id="discover-query" placeholder="e.g. a HIIT timer with voice cues" ...>
```

That string is hardcoded. The page has two watch lists — "Interval timers" and
"App blockers" — and the placeholder says "HIIT timer" no matter which one is
selected. It looks broken on the App blockers list.

**Fix:** make it generic and list-agnostic:

```html
placeholder="e.g. a store link, an app name, or just an idea"
```

Note that the neighbouring helper text on line 325 already uses
`{watch_list_label}`, which is correctly dynamic. Do not change that.

Also on line 382, the Tavily news-search placeholder is
`placeholder="e.g. Opal screen time funding"`. Change it to something generic
too, for the same reason:

```html
placeholder="e.g. a competitor's name plus a topic"
```

## 2. Competitor cards show no price, and no rating

The card is built in `prysma/web/app.py`, in the `comp_cards` loop near line 365.
It currently renders only: app name, a description, store links, and a
"listing changes" section. It does **not** show the app's price or its star
rating, even though both are already in the database.

Meanwhile the *discovery* candidate card (client-side, in `index.html` around
line 741) does show them:

```js
+ (c.rating != null ? esc(c.rating) + '★' : 'no rating')
+ ' · ' + esc(c.price || 'price unknown')
```

So the data is there. It just is not on the competitor card.

### Add a price line to each competitor card

Show three things per platform built from `app_store_listings`:

- the **star rating** (`current_rating`, e.g. `4.6★`)
- the **base price** (`current_price`, currently `Free` for every app)
- the **in-app purchase range** — see part 3, this is new data

Render it compactly, one line per platform, for example:

```
Android  4.6★  Free  ·  In-app purchases £0.59–£114.99
iOS      4.6★  Free
```

Keep the existing per-platform store link. Do not remove or reorder anything
already on the card.

## 3. Collect the in-app purchase range (new)

A "Free" app store listing means free to *download*. These apps make their money
on subscriptions, and the card does not say so. Google Play publishes the range
on the listing page, and I have verified it is present in the static HTML and
extractable.

The page contains a string of exactly this shape, and I confirmed the **first**
occurrence on the page belongs to the target app (the target's own data block
comes before the "similar apps" carousel):

```
£0.59 - £114.99 if billed through Play
```

Verified live against the app-blockers set on 28 Oct 2026 — every app returned a
distinct, plausible range:

| app | range |
|---|---|
| AppBlock | £0.59 – £114.99 |
| BlockSite | £0.49 – £204.99 |
| Freedom | £11.49 – £189.99 |
| one sec | £3.99 – £99.99 |
| Opal | £2.99 – £79.99 |
| ScreenZen | £4.79 – £19.49 |
| AppLock | £1.69 – £11.49 |
| Block - App & Site Blocker | £0.29 – £9.49 |
| App Blocker: Screen Time | £1.79 – £15.99 |

### Implementation

1. **Regex, module level**, next to the existing `parse_play_price()` helper in
   `prysma/agents/competitive_intel.py`. Add something like
   `parse_play_iap_range(text) -> Optional[str]` that returns the first match of:

   ```
   ([£$€]\s?[\d.,]+\s*-\s*[£$€]\s?[\d.,]+\s*if billed through Play)
   ```

   Return `None` when there is no match — a genuinely free app with no IAP has
   no such string, and that is not an error.

   Use the literal currency characters, not `\u` escapes, and no `re.ASCII`.
   The file already contains non-ASCII characters, so the encoding is fine.

2. **Scraper:** in `_scrape_google_play` (around line 103-190), call it and add
   `"iap_range": parse_play_iap_range(text)` to the returned dict.

3. **Database:** add a nullable `current_iap_range TEXT` column to
   `app_store_listings`. The schema starts near `prysma/storage/database.py:176`.
   Follow the existing migration pattern in that file — it already does
   `ALTER TABLE ... ADD COLUMN` defensively for other tables — so an existing
   database picks up the column without being recreated. **This matters: there
   is a live database with real data that must not be lost.**

4. **Storage path:** thread the value through the same route as `price` —
   `update_competitor_listing()` in `prysma/storage/database.py` (around line
   681) and the `_process_listing` call site in `competitive_intel.py` (around
   line 276).

5. **Display:** use it in the `comp_cards` builder in `prysma/web/app.py`.

## 4. Tests

Add tests, matching the style of the existing suite in `tests/`:

- `parse_play_iap_range` returns the range from a realistic snippet
- it returns `None` for a page with no such string
- it picks the **first** range when several appear (target app sorts first)
- the migration adds `current_iap_range` to an old database that lacks it, and
  does not lose existing rows

Run the full suite. It is currently **212 passing**. It must still pass.

## Do not

- Do not change the demo URL anywhere, or add it back to the README.
- Do not add authentication or change the rate limiting.
- Do not touch `prysma/security.py`.
- Do not reformat unrelated code or rename existing functions.

## When done

Report: which files changed, the test count, and the exact regex you used.
