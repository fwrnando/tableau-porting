# `.twb` structure: where things live

A `.twb` is a single XML document. A `.twbx` is a zip containing one plus its
extracts and assets.

## Top-level layout

```
<workbook>
  <document-format-change-manifest/>   preserve flags; add app-proven new features
  <repository-location/>               server provenance; drop when detaching
  <preferences/>
  <datasources>                        the data model(s)
  <datasource-relationships/>          the data BLEND, if any
  <shared-views/>                      blend metadata AND shared filter state
                                       (third piece of blend state lives inside
                                        worksheets: join-lod-include-overrides)
  <actions/>                           dashboard actions
  <worksheets/>                        every sheet
  <dashboards/>                        layout + zones
  <windows/>                           per-sheet UI state, card placement, viewpoints
  <external/>                          embedded images (base64) - often most of the bytes
                                       NB a UI save to plain .twb may drop these
</workbook>
```

## `<datasource>` children are ORDER-CONSTRAINED

This is enforced. Appending elements and leaving them at the end makes the
workbook refuse to open. The order:

```
repository-location, connection, utility-dimensions, dimension,
overridable-settings, aliases, column, column-instance, group, mapped-images,
drill-paths, unlinked-server-hierarchies, folders-common, folders-parameters,
actions, calculated-members, extract, layout, style, semantic-values,
date-options, default-date-format, default-sorts, field-sort-info,
datasource-dependencies, explainability, filter, object-graph
```

Sort children by this rank after any structural edit, including the **Parameters
datasource**. Appending parameter columns after its layout/style failed even when
the main datasource was sorted correctly. `<datasource-dependencies>`
by contrast is a loose choice-repetition: `column` and `column-instance` may
interleave freely (the source workbook will already show this).

## What lives inside a datasource

| element | holds |
|---|---|
| `<metadata-record class='column'>` | physical columns (`local-name`, `remote-name`, `parent-name`) |
| `<column>` | workbook-defined fields **and** physical-column overrides (caption, aliases) |
| `<column><calculation class='tableau'>` | ordinary calculated field, in `@formula` |
| `<column><calculation class='categorical-bin'>` | **grouped dimension** — logic is in child `<bin>` elements, `@formula` is empty, source field is in `@column` |
| `<group>` | sets; logic in nested `<groupfilter>` |
| `<drill-paths><drill-path>` | hierarchies — **nested in a container** |
| `<object-graph>` | logical model: `<object>` per table, `<relationship>` per noodle |

Two traps here:

- Filtering harvest on `class='tableau'` silently drops every grouped dimension.
- `findall('drill-path')` returns nothing because they sit inside `<drill-paths>`.

## Field reference forms

The same field appears in several syntaxes. A rewriter must handle all of them.

| form | where |
|---|---|
| `[field]` | formulas, `@column` on column-instance |
| `[field (table)]` | when a name exists on more than one related table |
| `[none:field:nk]`, `[sum:field:qk]`, `[yr:field:ok]`, `[usr:calc:qk]` | column-instances, shelves, encodings |
| `[federated.<id>].[none:field:nk]` | qualified ordinary dimension instance on shelves, filters, encodings |
| `[federated.<id>].[BRAND_NAME (group)]` | direct categorical-bin group reference; do not invent a `none:` instance |
| `[Parameters].[Parameter N]` | genuine cross-datasource reference — always keep |

Names are escaped inside brackets: `#` becomes `\#`, `%` becomes `\%`. Normalise
before comparing, or resolution checks throw false positives.

A declared column-instance's `@name` is not necessarily a decorated spelling of
its current field. Follow its `@column` binding before parsing a base-name
fallback; renamed/cloned table calculations can retain legacy instance names.

Categorical-bin groups need particular care: a base-name checker accepts
`[none:BRAND_NAME (group):nk]` because the group exists, but Desktop rejected that
wrapper with `9CA7205B`. Preserve the saved direct group reference. This exception
is about categorical-bin dimensions, not all fields with "group" in their names.

### The self-qualification rule

`[federated.X].[field]` is legal **only when X is a different datasource than the
one the expression belongs to**. It is how a blended calculation reaches the
secondary datasource.

Collapse two blended datasources into one and those references become
self-qualified. Tableau marks such a calculation invalid — a red pill, and any viz
using it renders blank rather than erroring. The fix is to strip the qualifier
inside `<calculation formula>` only. In worksheet XML the qualified form is
correct and must be left alone.

## Worksheets

```
<worksheet name='...'>
  <table><view>
    <datasources/>                      which datasources this sheet uses
    <datasource-dependencies datasource='...'>
        <column/>                       local declaration of every field used
        <column-instance/>              derivation instances
    <filter/>                           may interleave with sorts
    <manual-sort/>                      saved row order, in <bucket> elements
    <slices><column>...</column></slices> list of filtered columns; omit if empty
    <aggregation/>
  <join-lod-include-overrides/>         BLEND state - linking fields taken from the
                                        secondary datasource. Delete when collapsing
                                        a blend; invalid with one datasource, but only
                                        detected at extract time.
```

Worksheets may define calculations **locally** inside their dependency block.
Those are legal and will not appear in the datasource — a resolution check that
only looks at datasource-level definitions will report them as unresolved.

### Filter content model

`<filter>` is `(min?, max?, groupfilter, preset?, target*)` — **at most one direct
`<groupfilter>`**. Several members nest inside a single `function="union"`
groupfilter. Sibling member groupfilters make the workbook refuse to open, and the
bug is invisible until you write a filter with more than one member.

A **datasource-level** filter is often the better home for a scope rule than a
per-sheet filter: one element instead of one per worksheet, and it applies
everywhere. It lives directly under `<datasource>` (schema position: after
`datasource-dependencies`, before `object-graph`) and needs a matching
`<column-instance>` in the datasource.

**The reference form differs by context** — this catches people out:

| filter lives in | `@column` and `@level` |
|---|---|
| `<datasource>` | the **plain column**: `[retailer]` |
| a worksheet `<view>` | the **qualified instance**: `[federated.<id>].[none:retailer:nk]` |

A datasource filter names the column itself — not a `[none:…:nk]` column-instance,
and not datasource-qualified. Qualifying it resolves to `[ds].[ds].[field]` and
Tableau warns *"Field ... which is included for filtering does not exist"* — a load
**warning**, not an error, so the workbook opens with the filter silently inert.
Tableau also writes an optional `filter-group` attribute.

**Which column you filter on matters as much as the syntax.** In a relationship
model, a field from a *related* table is NULL wherever that table has no matching
row, and a categorical member filter excludes NULLs. Filtering a spine-shaped
model on, say, `[retailer (fact_table)]` silently drops every row the fact table
has no data for — in a forecast workbook that is the entire future. Filter on the
**spine's own** column, which is never null.

### Adding a filter needs three coordinated edits

1. the `<filter>` element in `<view>`
2. its declaration/dependencies in that sheet's dependency block (ordinary fields
   use a `<column>` + `<column-instance>`; retain direct categorical group syntax)
3. a `<slices><column>` entry

The slices content model is `(column+)`: **at least one column** if present.
After removing the last filter/slice, remove the container. `<slices/>` is valid
XML but rejected by Tableau (`D2E8DA72`). An order-pattern comparison alone misses
this minimum-cardinality constraint.

### Context filters

`context="true"` makes a filter evaluate first. It matters when the sheet uses
Top-N sets or FIXED LODs: those are computed *before* ordinary filters, so a plain
filter applied afterwards yields short top-N lists. Scope filters may therefore
need context, but do not copy the flag blindly. A brand/channel selector that a
full-market FIXED LOD must ignore **must not be context**. Review datasource and
extract filters too; both can remove inputs before that LOD. `filter-group` is
optional and records shared filtering, not order of operations.

### Workbook-wide (shared) filters

"Apply to all worksheets using this data source" filters live in
`<shared-views><shared-view name="<datasource>">` with their own dependency block, not in
any worksheet `<filter>` list. Each participating worksheet lists the filtered instance in
its `<slices>` (the target workbook put them first) and declares the field and its
dependencies. A sheet must not also carry a local filter on that field.

### Worksheet datasource list

`<view><datasources>` order matters: the first entry is the sheet's **primary**
datasource (blends list the primary first, then secondaries). Never put `Parameters`
first in a worksheet; dashboards, by contrast, list Parameters first.

### Worksheet dependency blocks

Children are sorted by `@name` (columns and instances interleave). Parameter copies
carry value, aliases and calculation but no `<members>` list. Sets are not
declared: their level field + `none:` instance and the fields in their order expression
are. Parameters reached by any formula get full copies in a separate block that comes
first.

## Dashboards, windows, sheet names

Sheet names appear as `@name` on `worksheet`, `zone`, `window` and `viewpoint`
(including inside `devicelayouts`), plus action bindings and exclusions. Dashboard
names have corresponding references. Use the complete known-binding recipe in
[transform-recipes.md](transform-recipes.md#renaming-sheets).

**Do not apply the sheet map to field `@caption`.** Captions can coincide with
sheet names. Field-caption cleanup is a separate, datasource-scoped operation;
see [authoring-cleanup.md](authoring-cleanup.md).

Navigation buttons are `type-v2="dashboard-object"` zones whose `<button action=
"tabdoc:goto-sheet window-id=&quot;{uuid}&quot;">` names the target window's
`<simple-id uuid>`, not its sheet name. Keep window simple-ids when copying windows.

Quick-filter zones carry the dropdown's value domain in `values`: `database` (all values,
including ones other filters exclude), `context` (all values in context), `relevant` /
`cascading` (only relevant values). To drop a member from one dashboard's dropdown,
exclude it with a context filter on that dashboard's sheets and use `context`.

Parameter controls are `<zone type-v2='paramctrl' param='[Parameters].[...]'>`
with the display label in a child `<formatted-text><run>`. Retitling a control in
place is far safer than deleting and re-adding a zone. Zones inside a
`layout-flow` container reflow automatically, so removing one is safe; zones in a
fixed layout leave a hole.

## Set controls: copy the exact UI location and mode

These shapes were saved by Tableau Desktop (Apple silicon) 2026.2. For a different version or control style, have the application save a
matching example. A worksheet card is not a dashboard zone, and dragging an
In/Out set pill to Rows is not the same as **Show Set**.

Datasource-level set, with `user` bound to
`http://www.tableausoftware.com/xml/user`:

```xml
<group name="[Brand Set]" caption="Brand" name-style="unqualified"
       user:ui-builder="filter-group">
  <groupfilter function="union" user:ui-domain="database"
               user:ui-enumeration="inclusive" user:ui-marker="enumerate">
    <groupfilter function="member" level="[brand_code]" member="&quot;BR1&quot;" />
    <groupfilter function="member" level="[brand_code]" member="&quot;BR2&quot;" />
  </groupfilter>
</group>
```

Use the actual selected codes/domain; the sample's members are not defaults.
Keep the `<group>` at datasource level. Worksheet dependencies need source fields
and the boolean keep calculation; do not duplicate a whole group there to try to
fix resolution. The app may also write an In/Out instance, without putting it on
a shelf:

```xml
<column-instance column="[Brand Set]" derivation="InOut"
                 name="[io:Brand Set:nk]" pivot="key" type="nominal" />
```

Preserve existing feature flags and add `<SetMembershipControl />` under
`document-format-change-manifest` when introducing the feature. The UI placements
are separate:

```xml
<!-- Worksheet window card: no mode attribute in the saved sample -->
<card param="[federated.X].[Brand Set]" type="setMembership" />

<!-- Dashboard zone: retain the target zone's existing id/geometry/layout -->
<zone name="Source worksheet" param="[federated.X].[Brand Set]"
      type-v2="setMembership" mode="checkdropdown">
  <!-- preserve the target's zone-style and layout attributes -->
</zone>
```

`checkdropdown` is the observed **multiple-values dropdown** dashboard mode, not
`compact`. Do not carry incompatible old filter attributes (`show-apply`, `values`,
or its mode) into a set zone. Preserve target zone IDs, worksheet name, parent
containers, geometry, styles and every device layout; template coordinates belong
to the example workbook, not the target. App-written wrapper zones can be nested:
do not flatten them or infer a universal wrapper rule from one sample.

Validate each control's qualified `param` against a set in **that datasource**,
and each dashboard set zone's `name` against its source worksheet. Names present in
some other datasource do not make the control valid. Preserve original shared
filter scope/defaults when replacing filters with sets; see
[transform-recipes.md](transform-recipes.md).
