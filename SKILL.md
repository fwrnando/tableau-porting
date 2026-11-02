---
name: tableau-porting
description: Port or modernize Tableau workbooks (.twb or .twbx) through validated XML transforms. Use for datasource migrations, moving dashboards into another workbook, calculation and filter changes, set controls, authoring-name cleanup, or dependency-aware removal of unused fields while preserving dashboards, extracts, assets, and the decks that screenshot them.
---

# Porting and modernizing Tableau workbooks

A `.twb` is plain XML. Worksheets, dashboards, layouts, formatting and calculated
fields may need to survive a model migration or a focused authoring cleanup. Keep
changes within the requested scope. Scripted XML transforms need both structural
and numerical validation.
Failures include rejected XML, valid-looking calculations with incompatible types,
and workbooks that open but silently lose market rows or show wrong numbers.

Two ideas carry most of the weight:

- A reference that **resolves** is not necessarily **legal**. The target field can
  exist while the reference syntax is invalid in its new context.
- A value that **exists** is not necessarily one that **matches**. Filters compare
  literals; if the new model spells the value differently, the filter silently
  returns nothing.

## Workflow

### 1. Survey before touching anything

Establish the shape of both sides. Never start editing from assumptions.

- Count worksheets, dashboards, datasources, calculated fields, parameters, sets.
- List each datasource's physical columns (from `metadata-record`) and its
  workbook-defined columns (calcs, groups, bins, sets).
- Identify how each model is assembled: physical joins, custom SQL, a data blend
  (`<datasource-relationships>`), or logical relationships (`<object-graph>`).
- List **workbook-wide shared filters** (`<shared-views>`; `twb_survey.py` prints them).
  They are in no worksheet's own filter list, and a scope such as
  `segment = "Core"` changes every total you compare against.
- For `.twbx`, inventory every archive member and connection, not just the main
  datasource. Preserve unrelated forecasts, credentials/connection configuration,
  extracts and assets; do not print secrets. Use a new, versioned output path.
- List what consumes the published dashboards: Rollstack decks, subscriptions. They
  keep their own copies of filter captions, values and crop boxes (failure mode 25 in
  [failure-modes.md](references/failure-modes.md)), so they are part of the port. Ask
  the user which decks use the workbook; the deck tool usually can't list them by view.

Report the scale honestly at this point. If a chunk of the workbook cannot be
ported, say so now and quantify it, rather than discovering it at the end.

### 1b. Verify the premise of the request

Requests arrive with assumptions attached — "it's the same fields", "this should
be a drop-in swap", "just point it at the new table". Check them before acting;
they are wrong often enough to matter, and the cost of checking is a query.

Compare **schemas** (which columns exist on each side) and **data** (row counts
and totals for the shared keys, by group). A swap can be mechanically clean and
still move headline numbers by a third, or silently widen scope. When the premise
turns out to be false, say so with the numbers and let the user decide — that is a
business call, not a technical one.

### 2. Establish the architecture is compatible

This decides whether the port is viable at all.

- **Blend -> relationships** can preserve separate measure grains. Verify linking
  keys, cardinality, unmatched domains, aggregation semantics and query/refresh
  performance; a relationship is not an automatic correctness or speed guarantee.
- **Blend -> physical join** risks multiplying rows and additive measures. Prove
  uniqueness at the join keys before adopting it.
- A "spine" table (a narrow key-only table others relate to) is a strong signal
  the target was designed for this.

For share dashboards with sparse brand rows, read
[market-share-selection.md](references/market-share-selection.md) before choosing
relationships, custom SQL, materialization or a Tableau-only solution. Establish
whether the industry field is additive, repeated, or a competitor residual first.
Respect this user's constraints; a rejected approach in one project is not a
universal ban. Creating warehouse tables or publishing requires task authority.
For unwanted residual/placeholder members, use that reference's display-only
filter recipe: hiding a mark is different from removing its calculation inputs.

### 3. Build and verify the field map

Map old identifier -> new identifier, then **verify every target exists** as a real
column in the target datasource. Do not trust the map until it is checked
mechanically.

- Distinguish bare columns from table-qualified ones (`[field]` vs
  `[field (table)]`). A name that appears only qualified must be mapped that way.
- If the source used a blend, its `<column-mapping>` is ground truth for semantic
  equivalence: two fields linked to each other mean the same thing, whatever they
  are called. Use it to resolve ambiguous mappings.
- Watch for concepts that exist under a different granularity (a "category" field
  in one model may be a "group" field in the other).

### 4. Check the blast radius of anything missing

For fields with no counterpart, trace consumers transitively through the calc
graph, then to worksheets and dashboards. Report exactly what is affected. This
is usually much smaller than it first looks, and it converts "this can't be
ported" into "these two sheets can't be ported".

### 5. Transform

Script it. Never hand-edit; you will need to re-run it many times.

Verify your XML library round-trips the file structurally before relying on it.
Then: harvest workbook-defined objects from the old datasource(s), rewrite their
references, merge them into the target, and rewrite every reference in worksheets,
dashboards, actions and windows.

See `references/transform-recipes.md` for the mechanics and
`references/twb-xml.md` for where things live. The traps that cost the most time:

- Harvest **all** calculation classes, not just the obvious one — grouped
  dimensions and bins use different `class` values.
- Some objects are nested in container elements and a direct child search misses
  them entirely, silently.
- `<datasource>` children must obey a **fixed schema order**; appended elements
  must be sorted back into place in **every datasource, including Parameters**.
- Remove `<slices>` when its last `<column>` is removed. A well-formed empty
  container still fails Tableau's `(column+)` content model.
- Preserve the app-written direct reference for categorical-bin groups; inventing
  `[none:Group:nk]` can resolve in a checker yet fail in Desktop.
- When collapsing a blend, references that named the *secondary* datasource become
  self-qualified and must have the qualifier stripped inside calculation formulas.

### 5b. When unsure of an element's shape, let the application write it

Do not reason out unfamiliar XML from the schema. Have the user make the change
once in the product's UI, then read back what it wrote and encode *that* in the
transform. It is ground truth, it takes one round trip, and it is faster than
guessing — a wrong guess costs a failed load and a user's time.

For set controls, request the exact **worksheet or dashboard location and display
mode** together. Showing a set is different from placing its In/Out pill on Rows.
Read the set-control recipe in `references/twb-xml.md` before implementing it.

The same applies in reverse: a file the application has re-saved is the best
reference you will get for how any element it wrote should look.

### 5b2. Transplanting views into a different workbook

When the target is another modern workbook (its model, shared filters and dashboards
stay), read [transplant-recipes.md](references/transplant-recipes.md): a native catalog
mapped from legacy ids, rebuilt dependency blocks, shared-filter subscription, collision
rules (filter groups, Measure Names aliases, names, images), retiring views and columns
the target extract does not have yet.

### 5c. Authoring cleanup is a separate operation

For names or unused-field cleanup, read
[authoring-cleanup.md](references/authoring-cleanup.md). Separate stable field IDs,
authoring captions and visible titles; trace datasource-scoped consumers before
deletion. A column-instance's actual `@column` can differ from its apparent name.
Do not treat a hidden worksheet or an absent shelf reference as proof of disuse.

### 6. Reconcile vocabulary

The step most likely to be skipped and most likely to bite. Two models rarely
spell their values identically: case, punctuation, padding, separators, or
outright different terms.

Values hide in **at least seven** places, and missing any one fails silently:

1. calculation formula literals
2. filter and set members (`<groupfilter member>`)
3. bin definitions (`<bin value>` and its `<value>` children)
4. **parameter domains** (`<member value>`) — parameters are data-independent, so
   they port verbatim and quietly carry the old vocabulary with them
5. display aliases (both `key` and `value`)
6. saved manual sort orders (`<bucket>`)
7. outside the workbook: the filter and parameter values that downstream decks
   store (step 1). A deck still sending a legacy `ACME MART` or `Kitchenware` never
   gets the native `Acme Mart` or `Housewares` slice.

Decide deliberately whether to translate the *literals* or normalise the *data*.
Normalising (e.g. wrapping the field in `UPPER()`) is a smaller diff but changes
what users see; rewriting literals preserves the new model's native display. Ask
if the user has a preference — it is a visible choice, not an internal one.

### 7. Validate in layers

Run all of these. See `references/validation.md` for implementations.

1. **Loads at all** — schema child order, well-formedness.
2. **References resolve** — every field reference names something defined.
3. **References are legal** — correct syntax for their context. Resolution alone
   does not catch invalid self-qualification.
4. **No stale identifiers** — old datasource ids, captions, table names gone.
5. **Structural integrity** — every dashboard zone names a real worksheet; no
   orphan windows; no duplicate definitions.
6. **Order patterns** — diff parent/child tag sequences against the source
   workbooks; anything appearing in neither deserves a look.
7. **Semantics** — query the warehouse directly and compare the new definition
   against the old one. This is the only layer that catches wrong *numbers*.
8. **Runtime and refresh gates** — confirm an actual worksheet query completed,
   then test extract creation/refresh and Server refresh when authorized. A local
   packaged extract does not prove credentials, drivers or remote refresh work.

The bundled validator (`scripts/`; usage in `scripts/README.md`) covers structural
layers, not Desktop's full schema or calculation type inference. Keep exact, reviewed
baseline warnings separate from new failures; never turn a broad warning suppression
into a passing result.

When a layer fails, or Desktop, an extract or a downstream deck shows a symptom, look
it up in [failure-modes.md](references/failure-modes.md) (symptom, cause, fix) first.

### 8. Verify meaning against the warehouse, not by reasoning

Whenever a mapping or a simplification is uncertain, go query the data. This is
fast, and it repeatedly beats inference. It will confirm equivalences, and it will
occasionally show that the *old* logic was wrong — a rewrite that reproduces every
closed period exactly but differs on the current one might reflect a correction,
different refresh timing or changed scope. Establish which before reporting.

Compare like periods and native grains: a monthly shipment total need not equal a
last-week compatibility value. Audit dated code/report mappings and compare share
numerators and denominators independently, not just ratios or grand totals.

## Reporting

State the blast radius early and the residual risk at the end. Distinguish clearly:

- **corrections** (numbers move because the old logic was wrong)
- **decisions** (numbers move because the user chose a different definition)
- **pre-existing breakage** (already broken in the source; verify before claiming)

Never report a port as verified when only its structure was checked. Say which
layers ran.

## Hard-won rules

- Treat both loud XML errors and silent semantic errors as regression-test inputs.
- "It opens and looks right" is a weak signal. Materialising the data — extract,
  publish — runs a stricter validator and is where leftover state surfaces.
- Validate mechanically; a mapping table you eyeballed is not verified.
- Filters that return zero rows look identical to filters that are working on
  empty data. For blank-but-loading, check literal domains and query/type errors,
  not just whether the field name resolves.
- A systematic fault hits hundreds of sites. When you find one instance, find the
  class and count it before fixing.
- Keep the transform re-runnable end to end. Patch the script, never the output.
  This also means an upstream fix — the user correcting the *source* workbook —
  flows through on the next run for free, and is usually better than replicating
  the same fix textually.
- Ask the user to close the workbook before you write to it. Two editors race, and
  the application wins.
- When a fix "doesn't take", prove which bytes are being read before changing
  anything else: modification time, checksum, and the raw text of the element.
- Resolve field references against the known names, not by parsing the derivation
  syntax. Wrappers stack (`pcto:cum:usr:X:qk`), carry `:vtnone`, and names contain `:`
  or look like tokens (`retailer`). An unmapped reference is silent until Desktop.
- Copy the shape of an existing element of the same kind rather than constructing
  it from first principles. Most loud failures in practice come from appending
  plausible-looking XML that violates a local content model.
