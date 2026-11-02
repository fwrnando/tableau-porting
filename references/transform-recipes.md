# Transform recipes

Generic patterns. `OLD_A` / `OLD_B` are legacy datasource ids, `TARGET` the new one.

## Shape of the whole thing

Build the output from the **workbook that holds the vizes** — worksheets,
dashboards, actions and layouts are the irreplaceable part. Swap the model
underneath it.

```
1. parse both workbooks
2. harvest workbook-defined objects from OLD_A / OLD_B
3. scoped structural deletions (obsolete blend entries, explicitly dropped sheets)
4. rewrite references across everything remaining AND the harvested fragments
5. merge harvested objects into the TARGET datasource
6. semantic fixes, vocabulary reconciliation
7. enforce schema child order
8. write
```

Rewriting before merging keeps the target datasource's own XML untouched by the
rewriter — otherwise its native field names can be caught by the map.

Keep the whole thing re-runnable from the original inputs. Patch the script and
re-run; never edit the output. You will run it dozens of times.

## Reference rewriting

Match bracketed identifiers and rewrite the inside, preserving wrappers:

```python
DERIV = re.compile(r'^([A-Za-z][A-Za-z0-9_]*):(.+):([a-z]{2})$')
OLD_ALIAS = re.compile(r'^(.*?) \((?:<legacy table patterns>)\)$')

def remap_base(base):
    m = OLD_ALIAS.match(base)          # strip legacy table qualifiers
    if m:
        base = m.group(1)
    return FIELD_MAP.get(base, base)

def remap_inner(inner):
    if inner in (OLD_A, OLD_B):
        return TARGET
    m = DERIV.match(inner)             # none:X:nk / sum:X:qk / yr:X:ok
    if m:
        return '%s:%s:%s' % (m.group(1), remap_base(m.group(2)), m.group(3))
    return remap_base(inner)

BRACKET = re.compile(r'\[([^\[\]]*)\]')
rewrite = lambda t: BRACKET.sub(lambda m: '[' + remap_inner(m.group(1)) + ']', t)
```

Apply to every attribute value and text node in the subtrees being ported. Only
bracket *contents* are touched, so string literals in formulas are safe. Guard the
datasource-name attributes separately so a bare id is replaced too.

Map entries whose target equals the source are harmless and worth keeping
explicit — they document that the name is unchanged rather than unmapped.

## Harvesting

```python
calc = col.find('calculation')
keep = calc is not None or col.find('aliases') is not None   # ANY class
```

Filtering on one calculation class drops grouped dimensions. Also harvest sets
(`<group>`) and hierarchies (from inside `<drill-paths>`, not as direct children).

Name collisions between two blended datasources are expected: the blend forced
parallel definitions of the same concept on each side. After remapping they
usually converge. Prefer one side consistently, count the collisions, and inspect
any whose formulas still differ.

When a harvested object's name collides with an existing target column, it is
usually a physical column carrying display metadata — merge its aliases onto the
target column rather than discarding it.

## Removing blend state

Inspect `datasource-relationships`, `shared-views` and worksheet-local
`join-lod-include-overrides`. Remove obsolete relationships and overrides when
collapsing that blend. **Do not delete all shared views:** they also store ordinary
workbook-wide filters in single-datasource workbooks. Preserve valid filter scope
and rewrite affected datasource/field references; remove only obsolete entries.

```python
# Only for a complete collapse of the workbook's blends:
el = root.find('datasource-relationships')
if el is not None:
    root.remove(el)

parents = {c: p for p in root.iter() for c in p}
for el in list(root.iter('join-lod-include-overrides')):
    parents[el].remove(el)
```

Leaving stale overrides behind can fail only at extract creation. Afterwards,
assert no obsolete blend references remain and every retained shared view resolves
to live datasources and fields. Preserve unrelated blends in a partial migration.

## Merging worksheet dependency blocks

Collapsing two datasources leaves two `<datasource-dependencies>` blocks per sheet
naming the same datasource. Merge into one, deduping children by (tag, name). Also
dedupe the sheet's `<datasources>` listing.

## Enforcing schema order

```python
RANK = {tag: i for i, tag in enumerate(DS_ORDER)}   # see twb-xml.md
for ds in datasources.findall('datasource'):
    kids = list(ds)
    ordered = sorted(kids, key=lambda e: RANK.get(e.tag, len(DS_ORDER)))
    if [id(x) for x in kids] != [id(x) for x in ordered]:
        for k in kids: ds.remove(k)
        for k in ordered: ds.append(k)
```

A stable sort preserves the relative order of same-tag siblings, which matters.
Run this over **all** top-level datasources, including `Parameters`, after the
last insertion. Sorting only the main data connection missed a failed-load bug.

After removing or replacing filters, update `<slices>` too. Remove the container
if it has no columns; do not serialize `<slices/>`.

## Stripping self-qualification

```python
SELF = re.compile(r'\[' + re.escape(TARGET) + r'\]\s*\.\s*')
for calc in root.iter('calculation'):
    f = calc.get('formula')
    if f and TARGET in f:
        calc.set('formula', SELF.sub('', f))
```

Formulas only. Never worksheet XML.

## Encoding-compatibility helpers

When the new model encodes a value differently, do not rewrite every consumer.
Add a helper calculation reproducing the old encoding and map the old identifier
onto it:

```
port_<concept> = <expression over new fields producing the OLD format>
```

Every downstream calculation then works unmodified. Verify against edge values.

## Renaming sheets

Use `twblib.rename_sheets(root, mapping)` for known bindings: `@name` on
`worksheet`, `dashboard`, `zone`, `window`, `viewpoint` and `exclude-sheet`, including
device layouts; action `source @worksheet/@dashboard`; and action `param` elements
whose `name="target"` carries the sheet name in `@value`. Audit other contexts in
the source instead of globally replacing matching strings.

```python
import twblib as T
T.rename_sheets(root, RENAMES)  # rejects collisions before mutating the tree
```

Do not rewrite field `@caption` as part of this sheet map. Derive names from the
sheet's own scope filters, row/column fields, mark type and host dashboard, rather than
from position. Guarantee uniqueness. Where the original author's distinction is
not recoverable from the XML, preserve their token rather than inventing meaning.

Embed the generated map as a literal in the transform so the pipeline stays
reproducible in one pass. A title using an automatic sheet-name token will change
visibly too; pin its original wording when the user wants authoring-only changes.
For field captions and unused-object deletion, read
[authoring-cleanup.md](authoring-cleanup.md).

## Building filters

Two things vary and both are silent when wrong: the **reference form** depends on
where the filter lives, and **several members must nest**.

```python
def categorical_filter(column, level, members, filter_group=None, context=False):
    """`column`/`level` are:
         datasource-level filter -> the PLAIN column   '[retailer]'
         worksheet filter        -> qualified instance '[federated.<id>].[none:retailer:nk]'
                                    with level '[none:retailer:nk]'
    """
    filt = ET.Element('filter')
    filt.set('class', 'categorical')
    filt.set('column', column)
    if filter_group:
        filt.set('filter-group', filter_group)
    if context:
        filt.set('context', 'true')

    def member(parent, value):
        gf = ET.SubElement(parent, 'groupfilter')
        gf.set('function', 'member'); gf.set('level', level)
        gf.set('member', '"%s"' % value)
        return gf

    # <filter> is (min?, max?, groupfilter, preset?, target*) - ONE groupfilter.
    if len(members) == 1:
        node = member(filt, members[0])
    else:
        node = ET.SubElement(filt, 'groupfilter')
        node.set('function', 'union')
        for value in members:
            member(node, value)
    node.set(UI + 'ui-domain', 'database')
    node.set(UI + 'ui-enumeration', 'inclusive')
    node.set(UI + 'ui-marker', 'enumerate')
    return filt
```

Build every filter through one helper. A single-member filter is valid as a bare
member groupfilter, so the union bug stays hidden until the first multi-member
filter — by which time the helper is copied in three places.

Choose the column deliberately too: in a relationship model a field from a
*related* table is NULL wherever that table has no row, and a member filter
excludes NULLs. Filter on the spine's own column.

## Syncing parameter declarations

Tableau copies each parameter's full definition into the
`datasource-dependencies` block of every sheet that uses it. After changing a
parameter's domain **or its default**, re-sync those copies or they keep the old
values:

```python
authoritative = {c.get('name'): c for c in parameters_ds.findall('column')}
for dep in root.iter('datasource-dependencies'):
    if dep.get('datasource') != 'Parameters':
        continue
    for col in list(dep.findall('column')):
        fresh = authoritative.get(col.get('name'))
        if fresh is not None and ET.tostring(fresh) != ET.tostring(col):
            dep.remove(col); dep.append(copy.deepcopy(fresh))
```

## Adding a filter to every sheet

Three coordinated edits per sheet (see `twb-xml.md`), plus:

- skip sheets with no dependency block for the target datasource — there is no
  field to filter on, and that is correct, not a failure
- insert the `<filter>` after the last existing filter
- choose context deliberately: market/date scope may need it, but brand/channel
  selection must remain ordinary when a full-market FIXED LOD must ignore it

## Replacing calculations and integrating set controls

Trace the transitive consumer graph before replacing an additive measure with an
LOD. A repeated view-level denominator needs `MIN`, not the old `SUM`, in both
formulas and shelf/encoding column-instances. Avoid rewriting unrelated SUMs.
Preserve time predicates (current/prior period, comparison year, rolling flags).

Synchronize authoritative definitions with worksheet and dashboard dependencies,
parameter copies, window cards/legends, Measure Values members, sorts, formats,
and every device-layout zone. A correct main datasource is not enough. Include
group source columns and set dependencies, not just the final measure. Copy the
app's direct reference for categorical-bin dimensions rather than manufacturing
ordinary `none:` instances.

Check declared datatype against the replacement result. An integer native unit
sum replacing a `real` calculation can produce a valid editor formula but an
invalid worksheet field. Either preserve the type with a justified cast (for
example `FLOAT(SUM(...))`) or update all dependent metadata intentionally.
Do not indiscriminately cast precision-sensitive numeric fields to float.

Read [market-share-selection.md](market-share-selection.md) for selection and LOD
scope, and [twb-xml.md](twb-xml.md) for the saved set-control syntax. Preserve each
original shared-filter scope and default selection: one common set per shared
scope, not independent sets on every sheet or one global set merging unrelated
controls. Once the set owns synchronization, remove the old dimension's
`filter-group` binding from its replacement boolean keep filter.

## Packaging and iteration

Open `.twbx` as ZIP, locate the `.twb` member (fail on ambiguity), and rewrite only
that member when data is unchanged. Preserve the other member names, relative
paths and payload bytes. Compare per-member hashes; ZIP compression/metadata can
change the outer archive hash without changing its contents. Do not assume the
extract is the only non-XML asset or that it contains only one table.

Write versioned outputs from known inputs; never overwrite a workbook Desktop has
open. When a user saves a UI example, use that as the syntax template, not as a
replacement for the production workbook and all its dashboards. If two outputs
should differ only in control mode, compare parsed structures (normalizing only
known benign declaration ordering) to prove no data/formula changes slipped in.

## Deleting a worksheet

Remove the `<worksheet>`, its `<window>`, any `<viewpoint>`, and any dashboard
zones naming it. Then confirm zero occurrences of the name remain anywhere.

## Watch out

A scratchpad file named after a stdlib module (`inspect.py`, `types.py`, `json.py`)
shadows it and breaks unrelated imports. Name transform scripts distinctively.
