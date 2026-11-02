# Failure modes

Ordered by how hard they are to notice. The loud ones are the lucky ones.

---

## 1. Schema child order violation — LOUD

**Symptom.** Workbook refuses to open. `Error Code: D2E8DA72`, "element 'column'
is not allowed for content model '(...)'", with a line/column pointer.

**Cause.** Elements appended to `<datasource>` land after `layout` / `style` /
`object-graph`, violating the fixed content model.

**Fix.** Sort every top-level `<datasource>` by the schema rank after every
structural edit, **including Parameters**. Sorting only the main data source
missed newly appended parameter columns after layout/style. The error message
itself lists the full legal order — read it.

---

## 1b. Element content-model violation — LOUD

**Symptom.** Same as above: workbook won't open, `Error Code: D2E8DA72`, but the
message names a *child* element rather than a datasource child. Typically one
error per occurrence, so the list is long.

    element 'groupfilter' is not allowed for content model
    '(min?,max?,groupfilter,preset?,target*)'

**Cause.** An element repeated where the schema allows one. The common case:
`<filter>` accepts exactly ONE direct `<groupfilter>`. A filter on several members
must nest them inside a single `function="union"` groupfilter — emitting sibling
member groupfilters is invalid.

```xml
<!-- WRONG: siblings -->
<filter class="categorical" column="...">
  <groupfilter function="member" level="..." member="&quot;A&quot;"/>
  <groupfilter function="member" level="..." member="&quot;B&quot;"/>
</filter>

<!-- RIGHT: one union wrapping the members -->
<filter class="categorical" column="...">
  <groupfilter function="union" user:ui-enumeration="inclusive" user:ui-marker="enumerate">
    <groupfilter function="member" level="..." member="&quot;A&quot;"/>
    <groupfilter function="member" level="..." member="&quot;B&quot;"/>
  </groupfilter>
</filter>
```

**Fix.** Read the content model in the error — it is the schema, printed for you.
Then copy the shape from an existing element of the same kind in the workbook: a
multi-member *set* already demonstrates the union nesting.

**Note.** A single-member filter works fine as a bare member groupfilter, so this
bug hides until the first time you write more than one member. Build filters
through one helper that handles both cases.

**Zero groupfilters is legal** in practice for `class="quantitative"` range
filters (they carry `<min>`/`<max>`), despite the printed model. Check against the
source workbook before "fixing" those.

### Empty encoding map after vocabulary cleanup

The first weekly v2 package failed with the bucket/multibucket content model:
removing a retired channel's color bucket left an empty `<map to="...">`.
Remove its enclosing encoding map too. Restrict bucket deduplication to the
intended sort dictionaries; a bucket is structural in other contexts. Encoding
maps require exactly one bucket or multibucket, but connection `<map>` elements
have a different content model. The validator deliberately checks only maps
under encodings, not every element named `map`.

### Empty slices after removing the last filter

`D2E8DA72`, `element 'slices' is not allowed for content model '(column+)'`, means
the optional container was left empty. It turned up in button worksheets after
their only filter was removed. Remove
the whole `<slices>` element if no columns remain. XML parsing and an advisory
child-order diff did not catch this; the validator now checks it explicitly.

---

## 2. Self-qualified references after collapsing a blend — SILENT-ISH

**Symptom.** Certain measures show as red/invalid pills; vizes using them render
blank. The workbook opens fine and other sheets look correct.

**Cause.** Calculations that reached the secondary datasource
(`SUM([federated.<secondary>].[field])`) become self-qualified once both sides are
one datasource. That syntax is only legal across *different* datasources.

**Diagnosis.** The pattern is diagnostic: measures comparing within one source
work, measures spanning the two old sources fail. Count occurrences of
`[federated.<target>].` inside `<calculation formula>`.

**Fix.** Strip the qualifier in formulas only. Keep `[Parameters].[...]`. Keep the
qualified form in worksheet XML, where it is required.

**Why validation misses it.** The referenced field *exists*. A resolution check
passes. The reference is illegal, not dangling.

---

## 2b. Qualification in the wrong context — WARNING, then silently inert

**Symptom.** The workbook opens but reports on load:

    Field '[ds].[ds].[none:field:nk]' which is included for filtering does not exist.

The doubled datasource id in the message is the tell. Being a warning rather than
an error, it is easy to dismiss — and the filter then does nothing.

**Cause.** Whether a column reference carries its datasource qualifier depends on
where it sits. A **datasource-level** filter must name the column bare; Tableau
supplies the context. A **worksheet** filter must carry the qualifier.

**Fix.** A datasource filter names the **plain column** (`[retailer]`); a
worksheet filter names the **qualified instance**
(`[federated.<id>].[none:retailer:nk]`).

**Getting the shape right.** Rather than reasoning it out, make the change once in
the product's own UI and read back what it wrote. That is ground truth, and it
took three wrong guesses here to arrive at what one save would have shown.

**Note.** This is the same underlying idea as failure mode 2: qualification is not
a property of the reference, it is a property of the reference's *context*. Three
distinct bugs in this family — self-qualified calc formulas, and both directions
of filter qualification. Worth a mechanical check rather than judgement.

---

## 2c. Filtering on a related table's column drops unmatched rows — SILENT

**Symptom.** A filter that looks correct empties part of the data — classically the
future half of a forecast workbook, or any period the fact table has no rows for.

**Cause.** In a relationship (noodle) model, a column from a related table is NULL
wherever that table has no matching row. A categorical member filter keeps only
listed members, and NULL is not one of them.

**Worked example.** A spine table carries date x product x customer for several
years including the future. The actuals table only has rows up to today. Filtering
on `[customer (actuals)]` is 100% NULL for every future-dated spine row, so the
whole forecast disappears — while past periods look fine, which makes it read like
a date bug rather than a filter bug.

**Fix.** Filter on the **spine's own** column, which exists for every row. Check
which table a field comes from before filtering on it: two columns with the same
name and different qualifiers are not interchangeable.

**Diagnosis.** Query the join: count spine rows where the related column is NULL,
split by period. If the future is 100% NULL, that is your answer.

---

## 2d. Blend leftovers inside worksheets — SILENT until extract time

**Symptom.** The workbook opens, renders correctly, and publishes. Creating an
**extract** then fails with a long list, one block per worksheet:

    The field <X> is not from the worksheet's data source.
    The following will be removed: ...

The named fields are always the same small set — and they are exactly the blend's
**linking fields**.

**Cause.** Blend state lives in **three** places, and the third is easy to miss:

| element | level |
|---|---|
| `<datasource-relationships>` | workbook |
| blend entries in `<shared-views>` | workbook; also stores non-blend shared filters |
| `<join-lod-include-overrides>` | **inside each worksheet** |

The third records which linking fields come from the *secondary* datasource. Once
both sides collapse into one, repointing its ids makes every entry claim a field
belongs to a secondary datasource that no longer exists.

**Why it hides.** Tableau tolerates the stale element on load and at query time —
there is simply nothing to apply it to — so the workbook looks perfect. Extract
creation validates references strictly and rejects them.

**Fix.** Delete every `<join-lod-include-overrides>` when collapsing a blend.
Nothing references them, and a genuine single-datasource workbook contains none —
which is the cheapest way to confirm the element is blend-only.

**Read the message literally.** "The following **will be removed**" is not a
warning about display: proceeding strips those fields from those worksheets. Since
linking fields are typically on shelves, you would get an extract plus quietly
broken vizes.

**Generalisable check.** If only one real datasource remains, obsolete relationship
and join-LOD override state must be absent. **Do not blindly delete shared views**:
valid single-source shared views preserve workbook-wide filter scope. Inspect
their datasource/field references and retain legitimate filtering state.

---

## 3. Vocabulary mismatch — SILENT

**Symptom.** A dashboard is blank. Status bar reads "0 marks". Filter controls
display plausible values. Nothing errors.

**Cause.** The models spell values differently — case, punctuation, padding, or
different terms entirely (a legacy warehouse's raw codes vs a curated model's
normalised labels). Filters compare literals, so they match nothing.

**Diagnosis.** For blank-but-loading, check the *values*, not just field existence.
Pull the field's actual domain from the warehouse and compare against the literals
in the workbook.

**Fix.** Either translate the literals or normalise the data. See failure mode 5
for where the literals hide.

---

## 4. Parameter domains carrying the old vocabulary — SILENT

**Symptom.** As above, and especially confusing because the control *displays* the
right thing — display aliases mask the underlying value.

**Cause.** Parameters are data-independent, so they port verbatim. A list
parameter whose members were data values now holds values that no longer exist.

**Diagnosis.** Audit every list parameter: dump its members and find which field
each is compared against in calculations. Check membership against the real
domain.

**Fix.** Retarget the domain to the new vocabulary. Drop aliases that have become
redundant. A parameter referenced by no calculation and no control is dead — still
worth fixing so it is not a trap later.

---

## 5. Values hiding in more places than expected — SILENT

**Symptom.** You rewrote the literals, most things work, one table still misbehaves
or a sort order silently reverts to alphabetical.

**Cause.** A data value appears in at least six distinct contexts. Rewriting only
formulas covers maybe half the sites.

**Checklist.**

| context | XML |
|---|---|
| formula literals | `<calculation formula>` |
| filter and set members | `<groupfilter member>` |
| grouped-dimension bins | `<bin value>` and child `<value>` |
| parameter domains | `<member value>` |
| display aliases | `<alias key>` **and** `@value` |
| saved manual sort order | `<manual-sort><bucket>` |

The manual sort is the sneakiest: buckets that no longer match do not error, the
sort just stops applying and rows quietly fall back to default order.

---

## 5b. Stale duplicate parameter declarations — SILENT, cosmetic-to-real

**Symptom.** A parameter's domain looks correct in the data pane, but tooling that
scans the file still reports the old values — and a future edit may resurrect them.

**Cause.** Tableau duplicates each parameter's full definition (value, members,
aliases) into the `datasource-dependencies` block of every worksheet and dashboard
that uses it. Retargeting only the authoritative copy in the Parameters datasource
leaves every duplicate carrying the old domain.

**Diagnosis.** Count occurrences of an old domain value across the whole document
after retargeting. If it is greater than zero, find which element owns each one —
they will be `<column>` elements inside dependency blocks.

**Fix.** After changing any parameter, re-sync its declarations: replace each
dependency-block copy with the authoritative one.

**Note.** Tableau reads the authoritative copy, so nothing visibly breaks. This is
mostly a trap for the next reader and for your own validation tooling — which is
exactly why it is worth fixing rather than explaining away.

---

## 6. String format mismatch — SILENT, and nastier than case

**Symptom.** Comparisons and string surgery return wrong results for *some* values.

**Cause.** The same concept encoded differently: zero-padded vs not, an integer vs
a string, an embedded separator, a different composite key layout. Existing
calculations do `LEFT`/`RIGHT`/`MID` and string comparisons on the old encoding.

**Worked example.** A week key stored as `'2026W33'` (padded, separator) in one
model and an unpadded integer `33` in the other. `RIGHT(...)` still looks right for
week 33 and breaks for week 6 — `'6' <= '26'` is false as a string compare, so a
half-year filter silently returns the wrong half.

**Fix.** Add helper calculations that reproduce the *old* encoding exactly from the
new fields, and map the old identifiers onto those. Every downstream calculation
then works unchanged. Verify the helper's output against the warehouse for edge
values (single digits, year boundaries), not just a typical value.

---

## 7. Dropped element classes during harvest — SILENT

**Symptom.** A field is undefined after the port, or a hierarchy vanished.

**Cause.** Over-narrow harvest filters. Grouped dimensions use a different
`calculation` class than ordinary calcs. Hierarchies are nested inside a container
element, so a direct-child search returns nothing and raises no error.

**Fix.** Harvest anything with a `<calculation>` of any class, plus anything
carrying aliases. Search containers explicitly. After merging, diff the object
inventory against the source.

---

## 8. Aggregate vs row-level when copying a calculation — SILENT

**Symptom.** A copied calculation errors, or double-aggregates.

**Cause.** A reference implementation may wrap its expression in an aggregate
(`SUM(...)`) while consumers in the target workbook apply their own aggregation,
giving `SUM(SUM(...))`.

**Fix.** Match the altitude of what you are replacing. Keep the calculation
row-level if its consumers aggregate it.

---

## 9. Top-N and LOD interaction with new filters — SILENT

**Symptom.** A "top 10" list shows fewer than 10 rows.

**Cause.** Top-N sets and FIXED LODs evaluate *before* ordinary filters. A new
plain filter drops rows after ranking.

**Fix.** Make filters defining the ranking scope context when that is the intended
behavior. This is not a blanket rule: brand/channel selection must stay ordinary
when full-market FIXED denominators must ignore it. Review the dependency and order
of operations before copying a context flag.

---

## 10. Pre-existing breakage misattributed to the port

**Symptom.** A dangling reference that looks like your fault.

**Fix.** Before claiming or fixing anything, check whether it is broken in the
*source* workbook too. Real workbooks accumulate dead calculations and references
to deleted fields. Report these as found, not introduced — and do not silently
"fix" them, since that changes behaviour the user did not ask you to change.

---

## 11. Testing against a stale copy — wastes a whole round trip

**Symptom.** You fix something, the user reports the identical error, and the file
on disk provably contains the fix.

**Causes, in order of likelihood.**

- **Reload ≠ reopen.** Refreshing or "reloading the data source" re-runs the query
  against the definition the application already holds in memory. It does not
  re-read the file. Only closing and reopening the workbook picks up an edit made
  on disk.
- **The application overwrote your file.** If the workbook was open when you wrote
  to it, saving from the application writes its in-memory copy back over your
  edit — silently reverting you.

**Fix.** When a fix "doesn't take", prove which file is being read before changing
anything: print the modification time and a checksum, and check the raw bytes of
the specific element rather than trusting your own parse. Then have the user fully
close and reopen — and warn them **not** to save on close if the stale copy is
still open.

**Corollary worth stating up front.** Ask the user to close the workbook before
you write to it. A file being edited in two places races, and the application
usually wins.

---

## 12. A UI save re-serialises the whole file

**Symptom.** After the user saves through the application, the file changes size
substantially and things you added are formatted differently — or absent.

**Cause.** The application rewrites the document in its own serialisation. It may
drop content it considers non-essential; embedded binary assets (images stored as
base64) are the usual casualty when saving to the plain, non-packaged format.

**Not a disaster, and often useful.** A UI save is the single best source of truth
for the shape of any element you are unsure how to construct: make the change once
in the UI, read back what it wrote, then encode that in the transform. It beats
reasoning from the schema.

**But re-verify afterwards.** Run the validation ladder over the re-serialised
file and check your inventory counts. Anything the application dropped that you
actually need must be restored by re-running the transform, which is another
reason to keep it re-runnable from the original inputs.

---

## 13. Commented-out code producing false positives

**Symptom.** Validation reports many unresolved references that turn out to be
harmless.

**Cause.** Tableau formulas keep `//` and `/* */` comments, and real workbooks are
full of commented-out history referencing long-dead fields.

**Fix.** Strip comments before analysing formulas. Report live and dead separately
— an unresolved reference in dead code is not a defect.

---

## 14. A grouped dimension exists but its invented instance does not — LOUD

**Symptom.** `9CA7205B`: `[none:BRAND_NAME (group):nk]` does not exist in the
datasource/database, although the group is defined.

**Cause.** A generic rewriter treated a `categorical-bin` group like an ordinary
dimension. Base-name resolution stripped the wrapper and falsely passed it.

**Fix.** Copy the direct `[federated.X].[BRAND_NAME (group)]` reference from the
saved source. Fix shelves, slices, filters, encodings and dependency declarations
systematically; do not add a fake physical field to the database. The validator
now rejects this observed wrapper, scoped to the defining datasource.

## 15. Valid calculation, incompatible declared datatype — runtime invalid field

**Symptom.** The editor says `MIN([Full industry])` is valid, but the measure pill
is red or the view blank. Desktop logs say the calculation's result type does not
agree with the field's declared type.

**Cause.** The replacement used native integer units while the preserved column
and its consumers declared `real`. XML resolution cannot detect type inference.

**Fix.** Preserve the intended result type at the helper (for example
`FLOAT(SUM([industry_units]))` inside FIXED), or intentionally update all metadata
to the new type. Consider numeric precision before casting. Verify a real query,
not just formula-editor validation.

## 16. Industry shrinks or disappears after brand/channel selection — SILENT

**Symptom.** Share looks plausible, but industry changes with brand selection;
products or periods with no own shipments disappear. Weekly can be affected too.

**Cause.** In an additive-plus-residual model, selected brands + COMP omit other
company contributions. Company-only filters lose entire markets. INCLUDE alone
also inherits sparse on-shelf brand dimensions; a FIXED value alone does not
restore the missing domain. A legacy zero-own-unit product helper can defeat a
correct COMP-retaining selector.

**Fix.** Verify row semantics and use the conditional recipe in
[market-share-selection.md](market-share-selection.md): complete market keys,
FIXED full industry, ordinary set selection OR COMP, nested EXCLUDE/INCLUDE and
MIN consumers. Audit all filters and exact dynamic on-shelf identifiers. Do not
hide industry-only markets, apply a blanket context flag or assume COMP equals
the entire industry. Repeated industry by brand is a denominator, not shipments.

## 17. Worksheet set example does not create the desired dashboard control

**Symptom.** In/Out rows appear, the dashboard control is missing, or the control
is a checklist rather than the requested multiple-values dropdown.

**Cause.** A set on Rows, a worksheet Show Set card and a dashboard set zone are
different structures. Copying filter mode `compact` or a worksheet-only example
does not reproduce a dashboard `checkdropdown` zone.

**Fix.** Ask for one saved sample at the exact location and display mode. Copy its
feature flag/control attributes, preserve target layout geometry and device zones,
and validate set/worksheet references. Keep the old shared selection scopes, not
the old filter-group binding on a newly boolean filter. See [twb-xml.md](twb-xml.md).

## 18. Bare percentage or a 100× formatting error

**Symptom.** A share displays `8.11` without `%`, or suddenly displays `811%`.

**Cause.** Confusing a ratio with a pre-scaled percent-number. Trial calculations
multiplied by 100; production fractions need percent formatting instead.

**Fix.** Use an unscaled ratio with `default-format="p0.00%"` for `8.11%`.
Audit formula, copied definitions and shelf formatting together. Handle percentage
points separately; do not apply a blanket percent format by caption substring.

## 19. "Open succeeded" log event masks a failed workbook/query

**Symptom.** Automation reports success, but the user sees a load error or red pill.

**Cause.** An open-workspace success event is not proof of XML load, valid fields
or worksheet query success. Logs rotate; rapid opens may cancel the first request.

**Fix.** Verify each revision sequentially. Correlate workbook name/time and query
hash, successful query completion, expected rows and no batch/InvalidField errors.
For nested LODs, replay the generated query against a copied extract and compare
native measures. See [validation.md](validation.md). Passing local query tests
still does not prove full refresh, Server connectivity or refresh performance.

## 20. Stacked derivations slip past the rewriter — SILENT until Desktop

**Symptom.** After a port, some table-calc or quick-table-calc pills still name the legacy
field (or are red), while ordinary `sum:`/`none:` pills mapped fine.

**Cause.** A regex for `prefix:name:suffix` reads `[pcto:cum:usr:Old:qk]` as prefix
`pcto` + name `cum:usr:Old`, and `[usr:Old:vtnone:qk]` as name `Old:vtnone`; neither is in
the field map, so both are returned verbatim. Legacy names containing `:`
(`day:sunday units`) and lowercase native names (`none:retailer:nk`) break the same way.

**Fix.** Resolve against the known names (`twblib.split_reference(inner, known_names)`,
`make_rewriter(..., known_names=...)`) and fail on any legacy-qualified token that does
not resolve. Regression: `test_twblib.ReferenceRewriteTests`.

## 21. A workbook-wide shared filter makes the scope comparison look 30-40% off

**Symptom.** The target datasource totals far more than the legacy dashboards; a
proposed scope fix "restores" parity.

**Cause.** The target dashboards are filtered by a `<shared-views>` filter (here
`segment = "Core"`, context) that no worksheet lists in its own filters.

**Fix.** Survey shared filters first; compare with that scope applied. Ported sheets
join it through `<slices>` + dependencies, and lose any local filter on the same field.

## 22. "The worksheet does not have a valid data source" — LOUD, one dialog per sheet

**Symptom.** On open, Desktop shows a dialog for every ported worksheet: *The worksheet
"X" contains errors. The following will be removed: The worksheet does not have a valid
data source.* Saving would delete the sheets.

**Cause.** The first `<datasource>` in a worksheet's `<view><datasources>` is its primary
datasource. A rebuilt list that put `Parameters` first left every sheet without a real
primary. (Dashboards do list Parameters first; worksheets must not.)

**Fix.** Data datasource first, Parameters after it. `twb_validate.py` layer 5 now rejects
a worksheet whose first datasource is Parameters (regression in `test_twb_validate.py`).
Tell the user to dismiss and quit **without saving**. The structural layers passed
before this rule existed: a rebuilt element can be well-formed, resolvable and still
semantically wrong for the application.

## 23. A FIXED anchor used by a context filter shifts inside its own context — SILENT, blank

**Symptom.** A scorecard renders its rows but every measure cell is empty; a sibling
sheet built from the same fields without that filter shows numbers. Desktop logs no error.

**Cause.** `[CW End Date] = { FIXED : MAX(week end with sales) }` fed both a *context*
filter (`[Is Selected Week]`) and the measures (`IF [Is Selected Week] THEN ...`). Tableau
evaluates the filter with the FIXED computed outside context (true current week), but the
FIXED inside the measures is re-evaluated *within* the context, where only last week's
rows remain, so "current week" becomes last week, "last week" points one week earlier,
and nothing matches. Visible only in the generated SQL: two subqueries for the same FIXED,
one with the context WHERE clause.

**Fix.** Anchor the row-level week logic on a parameter whose value refreshes from the
FIXED field when the workbook opens (`default-value-field`), as the legacy workbook did
with its week parameters. Diagnose by replaying the logged query against a copy of the
extract (validation.md): the replay returned NULL units and forecast for exactly the
affected sheets.

## 24. Two Measure Names aliases with the same text — one header loses its alias

**Symptom.** A scorecard header shows the field name ("CW or LW vs F...") while its
neighbour shows the intended label.

**Cause.** Tableau keeps one Measure Names member per alias text. Legacy workbooks keep
repeated header text unique with trailing spaces (`'WTD Forecast'`, `'WTD Forecast '`);
normalizing whitespace recreated duplicates.

**Fix.** Keep an explicit display-label table, unique by construction, and fail the build
on a duplicate alias value (including against the target's existing aliases).

## 25. Downstream decks keep the old names, values and layout — SILENT

**Symptom.** The ported workbook is right in a browser, but a deck that screenshots it
(Rollstack) shows the wrong slice or fails to update, or it crops the wrong piece of
the dashboard. Sometimes the view is missing from the deck tool's picker altogether.

**Cause.** The tool keeps its own copy of what the port changed, and reads the view list
live from the server:

| what the deck stores | what broke it |
|---|---|
| filter captions | legacy `Retailer L2` and `Channel` became `Retailer` |
| filter values | `ACME MART` → `Acme Mart`, `Kitchenware` → `Housewares` |
| parameter values | each value must be a member of the new parameter's list |
| crop boxes, in screenshot pixels | a retailer row and a filter block added above a section moved every crop below it |
| nothing (view list read live) | a workbook published without its sheets as tabs, or a dashboard left out of the publish, isn't offered |

**Fix.** Inventory the consumers before publishing: which decks show which views, with
which filters and crops. Port them with the workbook:
- translate captions and values;
- measure crops again on new screenshots;
- publish with sheets as tabs.

Fixed-size dashboards with fixed-height sections keep every section at the same pixels
whatever the filter, so a crop holds across filter values. Tools that screenshot after
applying a filter can capture before slow sheets re-query, so check filtered images more
than once.
