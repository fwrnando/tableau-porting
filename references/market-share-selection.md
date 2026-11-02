# Full-market share with sparse brand/channel rows

Use when a selection should change company shipments but retain the full industry
denominator, including markets with no shipments for the selected brand. This is
a conditional recipe, not a replacement for checking the target model's grain.

## Establish what the rows mean

Inspect raw rows and totals before choosing an LOD. Determine:

- Is industry additive across brand rows, repeated on every brand, or stored only
  on a market row? Does the competitor row hold the full industry or a residual?
- Which keys uniquely identify a market (product/report, period, geography,
  program, market channel)? Are any of these omitted from the view?
- Is there a retained row in **every** market when a company selection is empty?
- Which filters define the market, and which only select company shipments?

In one industry-data port, company rows contribute their shipments to industry and COMP
contributes the residual: `industry - all company shipments`. COMP own units and
own dollars are zero. Therefore:

- `SUM(industry)` over all rows is correct.
- `SUM(industry)` over selected brands + COMP is too small: unselected company
  contributions disappeared. COMP alone is **not** the full industry.
- Filtering to company rows removes industry-only markets entirely.

Prove these properties on the actual source; other models need other recipes.
Separate **value correctness** from **market-domain completeness**. A correct
FIXED value does not help if every row carrying a market is subsequently removed.

Preserve reporting scope as well as grain. A source may contain both a Total
channel and its component channels; including all of them double counts even if
each market key is unique. Encode verified geography/program/channel and rolling
history rules for live queries and future refreshes, not just in a one-off extract
build. Those legitimate scope rules must still retain the residual market rows.

## Tableau-only recipe for additive industry plus a retained residual row

The placeholders below stand for the full, verified market key list. Use native
identifiers, including any table qualifier. No custom SQL is embedded in Tableau.

1. Compute industry before ordinary company-selection filters:

   ```tableau
   // Full industry per market
   { FIXED [Report], [Period], [Location], [Market channel] :
       FLOAT(SUM([industry_units])) }
   ```

   Include other grain keys where applicable. The FLOAT here preserves `real`
   metadata in the worked case; choose types deliberately for another model.

2. Let users edit Brand and Company Channel sets. Apply an ordinary boolean
   filter retaining selected company rows **or** the residual row:

   ```tableau
   ([Brand Set] AND [Channel Set]) OR [brand_code] = 'COMP'
   ```

   Two filters, each `set membership OR COMP`, also work. The bypass must survive
   **both** filters. Keep them out of context and out of datasource/extract
   filters: those would restrict the input to FIXED. Market/date context filters
   remain an intentional scope decision.

3. Count each market once and remove company dimensions from the denominator's
   view grain:

   ```tableau
   // View industry — substitute all actual market keys and company dimensions
   { EXCLUDE [Brand code], [Brand name], [Brand group],
             [Company channel code], [Company channel name] :
       SUM({ INCLUDE [Report], [Period], [Location], [Market channel] :
           MIN([Full industry per market]) }) }
   ```

   The nested INCLUDE inherits the outer EXCLUDE scope. This behavior was checked
   with Desktop-generated query replay in the worked case. `MIN` inside INCLUDE
   deduplicates the repeated FIXED market value; SUM rolls markets up to the view.
   Re-check the generated query when adapting the grain or introducing other
   dimensions, sets, table calculations or filters.

4. Consume the repeated view denominator as `MIN([View industry])`, not SUM:

   ```tableau
   SUM([our_units]) / MIN([View industry])
   ```

   Mirror the recipe for dollars if present. Review zero-denominator behavior
   explicitly; do not blanket-fill absent markets or undefined ratios with zero.

Why not just INCLUDE? `{ INCLUDE market keys : MIN(full industry) }` retains
on-shelf brand/channel dimensions. A sparse brand then contributes only markets
where it has a row. The small product-only prototype can pass while the full
brand dashboard fails. EXCLUDE restores the common market scope.

Repeated full-industry totals on each brand row are intentional: this is the
common share denominator, **not brand shipments**. Caption it accordingly. This
does not synthesize missing brand-period marks; a complete zero-filled grid needs
an explicit scaffold/model decision. Do not promise that COMP retention creates
all missing combinations, or hide COMP with another row filter before the LOD.

## Dynamic dimensions require conditional scope

Existing dashboards often put a calculated dimension on Rows that switches among
Brand, Channel, Product, Period, etc. EXCLUDE matches the **exact field on the
shelf**, not just an underlying brand field used in its formula.

- Exclude the dynamic field only when its parameter selects brand/company channel.
- Keep it when it represents product, market channel, date or another market scope.
- Apply COMP bypass to a dynamic filter only in the company-selection modes;
  bypassing product/date selections would bring back excluded markets.
- Detect boolean branches such as `CASE [Show channel] WHEN TRUE THEN ...`, not
  just quoted selector values. Follow the dependency graph for less direct cases.
- An In/Out set pill on Rows introduces another dimension. It is not needed to
  show a set control and can alter denominator scope unless handled explicitly.

A practical compiler can create per-view calculation families: find the dynamic
fields used by that view, branch its denominator's EXCLUDE list by their selector
states, clone its industry-dependent calculation closure, and remap that view's
consumers. Preserve period predicates and formatting while doing so. Branch counts
can grow exponentially; do not copy a project-specific parser or a large branch
tree unexamined. Benchmark and consider a model change when complexity grows.

## Audit filters beyond the new selectors

Adding `OR COMP` is insufficient if another filter removes COMP or its markets.
Check datasource, extract, context, ordinary and measure filters, dashboard
actions, relevant-value helpers and null/zero suppression.

A legacy "relevant product" helper returned NULL when own units were zero;
it removed industry-only products on nine weekly sheets. Using the product
dimension itself retained those markets while preserving explicit product choices.
That intentionally widened the available product domain—report it as a semantic
correction, not a cosmetic rename. Remove obsolete company-only filters and clean
up their slices, dependency references and UI controls.

Keep company sales channel distinct from the market/reporting channel (for example
a reporting channel with Builder, Retail and Total members). Changing "Sales Office" captions to "Channel"
does not authorize merging those concepts. Prefer native modern labels and audit
aliases, filter members, group bins, parameter domains and sort buckets together.

## Hide synthetic members after calculation, not before

A retained residual row can appear as an extra brand/channel member, shifting
logos or showing a zero-own-unit row. That is a presentation issue: an ordinary
dimension filter can remove markets or change denominators. Hiding a header only
hides its label, not the mark. Do not suppress every zero or NULL indiscriminately.

When each displayed mark identifies one company member, a late table-calculation
filter can hide the synthetic mark while retaining calculation inputs. A tested
numeric-flag shape is:

```tableau
// Substitute the actual on-view dimension and verified synthetic member value.
LOOKUP(MIN(IIF(IFNULL([Displayed Company Member], '') = 'Residual', 0, 1)), 0) = 1
```

Filter to True. Add other verified code/name comparisons only when needed; the
sample value is not a universal reserved word. Copy a working table-calc field's
datatype, role, instance and addressing metadata, plus the coordinated filter,
dependency and slice edits in [twb-xml.md](twb-xml.md). A plausible
`LOOKUP(ATTR(...), 0) IN (...)` variant was rejected in one XML-generated workbook;
do not infer that syntax is universally invalid or trust formula text alone.

Audit dimensions actually on Rows, Columns and mark encodings, following their
dependencies. Do not infer display grain from Measure Names or from every declared
field. Apply suppression only to company-member views. For dynamic dimensions,
gate it to company-brand/channel modes; product, date and market-channel branches
must keep their own domain. Market/reporting channels are not company channels.

Check units, dollars, share, prior-period measures, subtotals/grand totals and other
table calculations. Mixed-member marks and addressing/partition changes need
explicit treatment. Confirm original query values are unchanged, only intended
marks are hidden, and non-company selector branches still display their members.
Do not expand this into a global filter on the residual source rows.

## Simplify only after proving equivalence

A native v2 field can replace legacy row-level decoding, date helpers or channel
mapping when values and types match at the same grain. Keep small compatibility
helpers when downstream identifiers/encodings are still relied on. Native fields
do not automatically replace selection-aware denominators, time comparison logic,
or display controls. Compare old and proposed calculations before deleting them.

Specific non-equivalences worth testing before a cleanup:

- Native `report_name` can change across historical report-code eras; replacing
  a normalization helper can split a product's history and break assumption joins.
- A native category can be coarser than the workbook's custom hierarchy. Replace
  hardcoded sets with native hierarchy predicates only after a full
  domain comparison; names alone do not establish membership equivalence.
- A native "core brand" flag need not mean "every non-competitor company brand." Check excluded
  brands and volumes before substituting it for a company-row predicate.
- Fiscal display strings, integer calendar fields and timestamp-to-date conversions
  are not interchangeable. Verify fiscal boundaries, timezone/DST edges and 52/53
  week assumptions. Absence of week 53 in the sample does not prove future safety.
- A null historical sales channel may warrant a preserved display fallback, not an
  invented modern channel assignment. Distinguish label cleanup from reclassification.

For unused-field deletion and authoring names, use the datasource-scoped consumer
graph and presentation safeguards in [authoring-cleanup.md](authoring-cleanup.md).

For shares, distinguish scale from format:

- A ratio `0.0811` with `default-format="p0.00%"` displays `8.11%`.
- A prototype `100 * ratio` already stores `8.11`. Remove that scaling before
  applying percent format, otherwise the result displays `811%`.
- Percentage-point differences are a separate measure/format decision. Do not
  change every field containing "share" or `%` by a blanket substitution.

## Alternatives and when to try them

| Approach | Benefit | Required checks / tradeoffs |
|---|---|---|
| Native single table + sets/LODs | Preserves packaged data and avoids a new model | Complete retained market domain, filter order, dynamic dimensions, query cost |
| Separate market fact + relationships | Explicit grain separation | Related-table filters, unmatched rows, key cardinality, live and refresh performance |
| Materialized presentation table | Moves repeated work out of interactive queries | Size, refresh time, freshness, assertions and authorized warehouse deployment |
| Brand × market scaffold | Produces marks for missing combinations | Fanout, denominator deduplication, row growth and zero vs missing semantics |
| Custom SQL | Quick query-shaped prototype | User acceptance, connection warning, maintainability and refresh cost |

In one port the user rejected custom SQL after slow relationships, and the
accepted implementation stayed on native extracts. That is case context, not a
general prohibition. A proposed warehouse presentation table was an option, not proof
that one was deployed or that performance improved. Benchmark representative
queries and full refreshes before claiming an approach is faster.

## Validation matrix

Check all, one, multiple and empty selections as supported by the UI, across brand
and company channel jointly. Include a selected brand with no shipments in an
otherwise nonzero market, an industry-only market, sparse brand periods, and both
product-only and brand/channel-detail views. Exercise dynamic selector branches,
annual/period rollups, prior-period/year measures and units/dollars separately.

Compare selected own measures and full industry independently at market and view
grain. A matching ratio alone can hide paired numerator/denominator errors. Test
both old and new report-code eras; one hard-coded product/report ID can omit a
later replacement. Use actual extract rows and Desktop-generated queries as
described in [validation.md](validation.md); a hand-written SQL analogue alone
does not prove Tableau evaluated the nested LOD as intended.
