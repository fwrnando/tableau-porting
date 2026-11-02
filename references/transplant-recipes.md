# Transplanting views into another workbook

Use when dashboards from a legacy workbook must live inside a *different*, already
modern workbook (its datasource, shared filters and dashboards stay as they are), rather
than swapping the model under the legacy workbook. The swap recipes in
[transform-recipes.md](transform-recipes.md) still apply to field mapping; this file
covers what is different when the target is someone else's workbook.

## Decide the unit and the anchor before mapping fields

- **Unit = dashboards.** Port a dashboard with every worksheet it hosts; skip scratch
  sheets that no dashboard shows unless asked. Count both before starting.
- **Prefer the target's existing building blocks** (its calendar, latest-date LODs,
  brand display field) inside new formulas, but give every *displayed* measure its own
  field when the target already shows a same-named field differently. Measure Names
  aliases are datasource-global (below).
- **Anchor row-level week logic on a parameter**, not a FIXED field, when any sheet
  filters on that logic in context: the FIXED is re-evaluated inside the context and
  shifts (failure mode 23). A dynamic parameter refreshed from the FIXED field on open
  keeps the data-driven default.
- **Time anchors are a semantic decision.** A legacy data-driven "current week" (latest
  week with sales) and a target parameter-driven "reporting week" differ on the day the
  week turns over. Keep one per dashboard family and say which in the notes.

## Write native definitions as a catalog, map legacy ids onto them

Keep native calcs in a data file (name, formula, type, folder, the legacy ids they
replace). The transform maps every legacy reference onto them and fails on anything
unmapped. Rules that paid off:

- Resolve references against the **known legacy names**, not by parsing derivation
  syntax: `pcto:cum:usr:X:qk`, `usr:X:vtnone:qk`, names containing `:` and lowercase
  physical names all defeat a regex. `twblib.split_reference(inner, known_names)`.
- Do the same on the native side when rebuilding dependencies: `none:retailer:nk` is
  `retailer`, not a stack of tokens.
- Enforce altitude: a legacy `sum:` instance may only map to a row-level native field,
  `usr:` only to an aggregate or table calc. Raise instead of rewriting the prefix.
- Carry default number formats and table-calc ordering from the legacy field when the
  catalog does not set them.
- Prune catalog fields nothing reaches (sheets, sets, parameter default fields) so
  retired helpers do not linger in the data pane.

## Collapse the blend — and expect rows the blend never showed

The secondary only contributed where the primary had rows at the active link fields
(the view's linked dimensions plus `join-lod-include-overrides`). A native table built
as a FULL OUTER JOIN of actuals and forecast has forecast-only rows: future days of the
current week, products with a forecast and no sales. Consequences seen:

- by-day tables grew columns for days not yet reported → filter those sheets to rows
  with actuals (a per-sheet override of the week filter);
- a scorecard can gain a row with forecast but no actuals — usually more correct;
  mention it;
- the blend's forecast was implicitly limited to the primary's product scope; the
  native one is limited by the target's filters instead. Verify both sides' scope.

## Rebuild every dependency block

Delete **all** legacy `<datasource-dependencies>` in a ported sheet or dashboard,
including the Parameters copies (their `default-value-field` still names legacy
calcs), and regenerate from the native definitions:

- `<column>` copies of every field reached through formulas and table-calc ordering
  fields; parameter copies for every parameter reached;
- sets are not declared; their level field, its instance and their order-expression
  fields are;
- reuse rewritten legacy `<column-instance>` elements (they carry table-calc addressing
  and `visual-totals`); generate only plain `none:` dimension instances;
- children sorted by `@name`, Parameters block first, right after `<datasources>`.

## Join the target's shared filters

Workbook-wide filters live in `<shared-views>`; a sheet participates through `<slices>`
entries (listed first, in the target's order) plus dependency declarations. Survey them
first (`twb_survey.py` prints them). A ported sheet must not also keep a local filter on
the same field: remove the legacy local filter (e.g. Brand) and let the shared one apply.
Its dashboard filter zone then drives the shared filter. Tell the user that its scope is
now workbook-wide.

## Things that collide when two workbooks meet

| object | rule |
|---|---|
| sheet / dashboard / calc / parameter names | check against the target first; fail on collision |
| `filter-group` ids | renumber ported ones past the target's maximum, keeping legacy groupings |
| Measure Names aliases | datasource-global: add only keys absent from the target. Alias TEXT must also be unique (Tableau drops a duplicate): keep an explicit label table, use trailing spaces for repeated headers, fail on duplicates |
| package members (images) | add new ones; a same-named member must be byte-identical |
| manifest flags | add the flags the ported XML uses (e.g. `CascadingFilters` for `ui-domain="cascading"`) |

Window `simple-id` uuids must be preserved: dashboard navigation buttons address
windows by uuid (`tabdoc:goto-sheet window-id="{...}"`), not by name, so renaming sheets
does not break them but regenerating ids does.

## Removing a retired view

Drop the dashboard, its sheets and windows; then remove zones on the remaining
dashboards that point at it — navigation buttons targeting its window uuid, footnotes
explaining its measures — matching each zone's **own** `<button>` / `<formatted-text>`.
`zone.iter('button')` also matches every container holding such a button and removes
whole layout columns. Remove the same zone ids from device layouts and any layout
container left with no child zone. Mark the retired legacy fields as dropped so their
Measure Names members, sort buckets, style rules and legend cards are removed and
anything else fails loudly. Compare zone counts per dashboard before and after.

## Physical columns the target extract does not have yet

Let the application write a new warehouse column: deploy the warehouse change, refresh
the target's extract in Desktop, save, re-run the transform against it. Desktop writes
the two column maps and the live and extract `metadata-record`s, but **no `<column>`**
unless something overrides the field: detect readiness from metadata records, and copy a
sibling's `<column>` if the target captions its physical fields. Until then emit the
dependent calcs as typed placeholders (`FLOAT(NULL)`, formula kept as a comment) so the
workbook opens cleanly.

## Labels and names

- Relabel unwanted Null members (placeholder products with no attribute) with a
  display calc (`IFNULL([field], 'Uncategorized')`) swapped onto row and column
  shelves, sorts, `<subtotals>` (the Total row names the shelf field) and style rules
  only. Add the calc and its `none:` instance to each sheet's dependency block in name
  order, and apply it to every sheet that shows the field, not only the one in the
  screenshot: the same Null row can sit on dozens of sheets. Keep filters and slices
  on the source field so shared filter groups and dashboard quick filters keep matching; leave the warehouse alone unless asked.
- Dynamic parameters (`default-value-field` → a FIXED, single-valued calc) are a native
  way to keep date labels in dashboard text (`CW Ending: <[Parameters].[CW Ending]>`).
- Rename to the target's style with a literal map applied by `twblib.rename_sheets`
  after the port, and require every ported sheet to have an entry.

## Verify

Structural: `twb_validate.py` plus a port-specific check that every instance a sheet
uses is declared in its own dependency block, instance suffixes match field types, every
native formula resolves and no legacy ids remain. Semantics: emulate the legacy blend
(join at the active link fields) over copies of the legacy extracts and compare per
retailer/period with native SQL; explain every difference as scope, freshness, source
change or correction. Runtime: a clean Desktop open with zero query errors still showed
blank scorecards (failure mode 23); replay the logged SQL for at least one sheet per new
calc family and compare with the native SQL ([validation.md](validation.md)).
