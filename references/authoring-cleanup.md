# Authoring names and unused-field cleanup

Use for workbook housekeeping, not as an automatic step in every datasource port.
Establish whether the user wants authoring names, dashboard wording, or both to
change. Keep an immutable parsed baseline and an explicit old-to-new map.

## Separate names from presentation

- A worksheet's `@name` is its authoring identity and a reference target. Follow
  the complete sheet-reference rewrite in [transform-recipes.md](transform-recipes.md).
- Field, parameter and set `@caption` values are authoring names; bracketed IDs
  bind references. Keep IDs stable for cosmetic cleanup unless ID rewriting is
  explicitly needed. Generated IDs containing old words need not be UI defects.
- Captions also feed automatic headers, tooltips, Measure Names and control
  titles. Preserve requested display wording with explicit titles/member aliases,
  not by assuming a caption change is invisible. Snapshot old captions **before**
  mutating definitions, and synchronize authoritative and local declarations.
- Preserve existing formatted titles. For default dashboard control headings,
  copy app-written `custom-title="true"` and `formatted-text` structure while
  retaining geometry, control mode, scope and all device layouts.
- Parameter member `alias` is display text; `value` and the default drive formula
  branches. Rename aliases without changing selector values or domain membership.

Derive names from formulas, shelves, scope filters, mark types and host dashboards.
Replace `copy`/numbered suffixes with a supported distinction: Units vs Dollars,
Bars vs Line, With Goals, or a dashboard-specific scope. A single-row fallback is
not necessarily a total. When the distinction is unclear, inspect rather than
inventing a meaning. Check uniqueness within each datasource and the sheet namespace.

Keep distinct business concepts explicit, such as **Sales Channel** versus
**Market Channel**. Audit native-field captions, selector aliases and controls,
not just worksheets. Do not rename data values or merge concepts to simplify UI.

## Prove disuse with a consumer graph

1. Index authoritative definitions and worksheet/dashboard-local declarations by
   datasource and field ID. Preserve local scope when declarations differ. Include
   all calculation classes, categorical-bin source fields, sets and parameters.
2. Resolve each `column-instance @name` through its actual `@column` before walking
   dependencies. An instance named `[usr:Old Helper:qk:1]` can point to
   `[Replacement Helper]`; stripping its wrapper would follow the wrong field.
3. Start from real consumers: shelves, encodings, filters/slices, actions, labels,
   sorts, formats, controls, shared views and model references. Ignore built-ins
   such as Measure Names as dependency shortcuts to every measure. A declaration
   or folder entry alone is not evidence that a field is used.
4. Traverse formulas, group/bin/set definitions and parameter dependencies to a
   fixed point. Conservatively retain fields whose consumers cannot be resolved;
   do not use a global bag of same-named fields from unrelated datasources.
5. With cleanup authorization, remove only unreachable calculated fields or
   parameters and their unused local copies, instances and folder entries. Do not
   delete physical columns, extracts or auxiliary datasources as a side effect.

Hidden worksheets can supply dashboard views, controls or actions. Delete a blank
sheet only after checking its marks, shelves and every inbound reference; remove
its remaining UI state using the worksheet-deletion recipe.

For all retained objects, compare calculation trees, selector values/defaults,
existing filters, connections and package payloads against the immutable baseline.
Record removed IDs/captions and keep recoverable backups. A naming/deletion pass
must not silently change measure logic. Validate representative affected views in
Desktop; a structural reference checker is not a liveness or type compiler.
