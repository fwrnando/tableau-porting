# The validation ladder

Run every layer. Each catches a different class, and the cheap ones do not
subsume the expensive ones. Report which layers actually ran — "validated"
without qualification is misleading when only structure was checked.

---

## Layer 0 — round-trip fidelity (before you start)

Confirm your XML library preserves the document structurally. Parse, write, parse
again, compare a recursive signature of (tag, sorted attrs, text, children).

If this fails, stop and fix it. Everything downstream assumes it.

Register the workbook's namespace prefix so it round-trips. Attribute quoting and
entity form may change; that is fine, structure is what matters.

---

## Layer 1 — does it load

Schema child order (see `twb-xml.md`) plus known content models. These catch loud
load errors; later reference/runtime checks can fail loudly too.

Two distinct checks live here:

1. `<datasource>` child order, including **Parameters** (see `twb-xml.md`).
2. **Element content models** — most usefully, no `<filter>` with more than one
   direct `<groupfilter>`, no empty/non-column `<slices>`, and exactly one
   bucket/multibucket per encoding map. Parsing cleanly proves nothing about those
   constraints.

`twb_validate.py` covers these, not the full Tableau schema. Extend its guards as
you meet new ones — every
`D2E8DA72` message prints the content model it enforced, so the rule is handed to
you.

---

## Layer 2 — do references resolve

Collect every defined object: datasource columns, groups, drill paths, parameters,
**and worksheet-local declarations**. Then walk every reference and check it names
something.

Handle before comparing:

- derivation wrappers — `none:X:nk`, `sum:X:qk`, and table-calc suffixes
- escaping — `\#` and `\%`
- table-qualified names — fall back to the bare name
- comments — strip `//` and `/* */`, and report live vs dead separately

Resolve declared column-instances through their `@column`, not just a base name
parsed from `@name`; legacy instance names can point at replacement calculations.
Keep datasource/local scope when building a dependency graph for deletion. The
bundled checker is not a substitute for that graph.

Expect false positives from built-in placeholders (e.g. multi-field shelf markers)
and from datasource/table qualifiers. Whitelist them explicitly rather than
loosening the check.

---

## Layer 3 — are references legal

Resolution is not legality. The specific check that matters after collapsing a
blend: no `[federated.<target>].` qualifier inside any `<calculation formula>`.

After a complete collapse, Parameters should be the only cross-datasource formula
qualifier. Genuine retained blends are an exception that the current conservative
validator flags for review; never strip their qualifiers indiscriminately.

Also reject ordinary `none:...:nk` wrappers on categorical-bin groups. Their direct
references are legal even without such an instance; inventing a wrapper can pass
base-name resolution and still fail Desktop. Inspect definitions in the reference's
own datasource, not a global bag of same-named fields.

---

## Layer 4 — no stale identifiers

Count occurrences of every old datasource id, old datasource caption, and old
source-system table name across the whole document. All should be zero.

Captions are easy to miss: rewriting a datasource `@name` leaves `@caption`
displaying the old model's name in the data pane.

---

## Layer 5 — structural integrity

- every dashboard zone naming a worksheet resolves to an existing worksheet
- no orphan windows or viewpoints
- no duplicate definitions inside a single dependency block
- expected counts of worksheets, dashboards, parameters, sets
- required sections still present
- set-control params resolve to sets in their named datasource; dashboard set
  zones name a real source worksheet
- retained `shared-views` resolve to live sources; presence alone is not stale blend
  state

---

## Layer 6 — order-pattern diff

A strong general check for structural edits.

For every parent tag, collect the sequence of child tags (run-length collapsed) in
the ported file and in **both** source files. Report any pattern present in the
output but in neither input.

Most hits are benign — a subsequence of an original after deletions, or a
combination of optional elements that no single source happened to have. But it
reliably surfaces genuinely novel structure, which is where corruption hides.
This layer is advisory and does not check minimum cardinality: it did not reject
empty slices. Add a specific failing regression when a real load error exposes a
new invariant.

---

## Layer 7 — vocabulary and domains

For every literal compared against a field, and every list parameter domain,
confirm the values exist in the new model. Query the warehouse for real domains.

Cover all six hiding places from `failure-modes.md`.

---

## Layer 7a — read the extract itself

The single highest-value check in this ladder, and the one that caught a silently
broken build twice. An extract file is directly readable with the vendor's Python
API (`tableauhyperapi` — a plain download, no server required):

```python
from tableauhyperapi import HyperProcess, Connection, Telemetry, CreateMode
with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
    with Connection(endpoint=hp.endpoint, database="x.hyper",
                    create_mode=CreateMode.NONE) as c:
        for t in c.catalog.get_table_names("Extract"):
            n = c.execute_scalar_query(f"SELECT COUNT(*) FROM {t}")
```

Copy the file first if the application holds a lock. What to assert:

- **row count per table**, against the warehouse
- **min/max of every date column** — truncation is the classic silent failure
- **distinct values of any filtered dimension**
- **the collapse indicator**: in a spine model, if the spine's row count equals a
  *related* table's row count exactly, investigate whether a left join degraded to
  an inner join and dropped rows that only the spine owns

Treat that last pattern as a warning, not proof by itself; verify missing keys.
Discover actual schemas/table names through the catalog rather than assuming a
single `Extract.Extract`. A package can also contain unrelated forecast tables.
For XML-only modernization, hash every non-TWB package member to prove it stayed
unchanged, and compare original connections/parameters/sheet inventories.

The same technique reads a *published* extract — download the workbook and unzip
it. And the pre-migration extracts are the best available baseline for "what did
this look like before", including row counts the old source may no longer expose.

---

## Layer 7b — the stricter gates: extract and publish

Opening cleanly is a weaker check than it feels. Some references are only
validated when the product **materialises** the datasource — creating an extract,
or publishing with one. A workbook can open, render correctly and publish, then
fail at extract time on state that was invalid all along.

When authorized, test a fresh extract/refresh as a separate gate. If the user will
publish and refresh on Server, mark that gate pending until they report results.
Do not publish or deploy as a side effect of a diagnosis or documentation task.
Existing local Hyper queries do not test Server credentials, network access,
connector/driver availability or full-refresh performance. Audit every connection,
including retained auxiliary legacy-database and spreadsheet sources, before describing the refresh
path as migrated.

### Actual Desktop query evidence

An `end-workspace.open-workbook` event with `a.rk=ok` occurred even for a failed
load/invalid field. A finished thumbnail is also insufficient. Confirm the exact
workbook revision, then follow `begin-protocol.query` to its matching query hash
and successful `end-protocol.query`, with nonempty expected rows. Check batch
summaries (`qp-batch-summary`) for errors and scan `InvalidField` and
`detailed-error-msg` events. A valid calculation in the editor can still disagree
with its XML-declared datatype when the worksheet evaluates it.

Also confirm successful worksheet computation, not just its data query. Some
`InvalidField` events have no workbook context: include them by process ID and
the bounded open/query time window. Filtering logs solely by workbook name can
discard the actual failure. No query after a launch is an unverified attempt,
not proof of an empty dataset or a successful test.

On macOS, logs are under `~/Documents/My Tableau Repository/Logs/`.
Desktop rotates `log.txt` to `log_bk.txt` at launch, so a byte offset taken before the
launch points past the end of the new file: select a session by timestamp instead.
Load dialogs such as "contains errors ... will be removed" are not written to the log;
ask the user what Desktop showed, and never let them save a workbook that raised one.
They rotate: correlate workbook name, timestamp and query hash, not a fixed log
filename. Open two candidate workbooks sequentially and verify each; rapid launch
requests to a single Desktop instance can replace/cancel the first. If an app
alias fails, use the actual installed application path rather than assuming a
version or architecture.

### Replay generated SQL against a copied extract

For difficult nested LODs, capture Desktop's generated SQL and replay it using
`tableauhyperapi` against a temporary copy of the packaged extract. This tests the
actual query plan semantics; handwritten SQL alone only tests an intended analogue.
Use `Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU`. Open `Connection(endpoint)` without a
database, `attach_database` the extract copy, and prefix the logged `"Extract".` schema
with the alias; attaching the database you connected to fails. Keep evidence SQL separate from
the workbook: query replay does **not** mean adding a custom SQL connection.

Tableau sometimes populates temporary group/set mapping tables through API calls,
so the log contains CREATE/empty SELECT but no inserts. Reconstruct **only those
mapping rows** from the exact package's categorical bins/set membership and the
necessary source domain; preserve quoted native column aliases and any
`_Tableau_join_flag`. Verify unique keys/no fanout. Then execute the worksheet SQL
unchanged and report that mapping reconstruction explicitly. Do not invent missing
fact data or claim a verbatim execution if the query itself was altered.

Follow nested categorical-bin mappings recursively and retain ungrouped identity
members from the actual domain; omitting them can lose rows on an INNER mapping
join. Require replay row counts to match Desktop's query event. Two empty results
are not an equivalence proof when the source view should contain data.

An in-memory/federated Data plan may wrap an underlying Hyper query. If replaying
only that subquery, label the evidence accordingly; identify any constants or
operations left to Desktop rather than claiming full-plan replay. Match original
columns by metadata and compare keyed rows or multisets, preserving duplicates.
For display-only filters, compare pre-hide measures separately from keep flags and
the resulting visible domain; test totals and table-calc behavior in Desktop too.

Compare returned own units/dollars and industry units/dollars separately against
native-grain sums for the same scope. Identify result columns from query/schema
metadata, not presumed column order. Save workbook and query hashes, filters,
expected/actual values, row counts and any reconstruction assumptions.

---

## Layer 8 — semantics

The only layer that catches wrong numbers, and the one most often skipped.

Reimplement both the old and the new definition in SQL against the warehouse and
compare over a meaningful window, grouped by period.

Interpreting the result:

- **Matches in the tested scope** — equivalence established for that scope, not
  all interactions.
- **Matches historical periods, differs on the current one** — investigate old
  logic, data freshness, incomplete periods and changed scope before assigning blame.
- **Differs everywhere** — stop and establish whether grain, mapping or the intended
  definition changed. Do not ship an unexplained difference.

Prefer a per-period table over a single total; a single total can net out
offsetting errors.

For share dashboards use the selection matrix in
[market-share-selection.md](market-share-selection.md). Include industry-only
markets, report-code changes, dynamic dimensions and independent numerator/
denominator comparisons. A month total versus a last-week total is not a valid
equivalence check; inspect source period logic and submission lineage. A packaged
extract's history window and the full warehouse history are different scopes too:
compare within one.

Say what a check actually proves. A match against another period or a related source
supports the method, not that period's numbers; a source you could not reach is not
a check at all. A later year's source files agreeing with the warehouse supports the
aggregation rule; it does not confirm an earlier year's numbers.

---

## Sanity checks on the checks

Two failure modes of validation itself, both seen in practice:

1. **Scope too narrow.** A check reporting "0 problems in live calculation code"
   while problems sit in filters, bins, parameters and sort orders. Enumerate the
   contexts a thing can appear in before concluding it is absent.
2. **False positives dismissed too fast.** Escaping artifacts and built-in
   placeholders produce noise, and it is tempting to wave the whole list away. Fix
   the checker so its output is trustworthy, then read it. A real defect hidden in
   a list of known-noise entries will be missed.

Record exact baseline warnings with their counts and compare new vs baseline;
fail on new findings. Do not globally whitelist a substring such as a forecast
caption containing `<<0`. The current validator's base-name resolution is not a
complete datasource-scoped compiler, nor does it infer calculation types. Its
passing output is a structural check, not proof of render, numbers or refresh.

Keep minimal known-bad and known-good XML fixtures for deterministic invariants.
Run `python -m unittest discover -s scripts -p 'test_*.py'` from the skill folder,
then run the validator on real source/output pairs and inspect baseline deltas.

If a final revision only changes approved labels, prove that claim with a parsed
diff normalizing exactly those labels—not all captions, formulas or ordering.
Before an authorized replacement, confirm the source has not changed since the
baseline, back it up, and install the exact candidate whose checksum was tested.
