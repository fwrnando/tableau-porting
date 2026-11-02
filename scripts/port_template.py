#!/usr/bin/env python3
"""TEMPLATE for a workbook port. Copy, fill in the CONFIG block, run repeatedly.

    uv run --no-project python port_template.py

This is a skeleton, not a runnable tool - the field map and semantic fixes are
specific to every migration. The mechanical parts live in twblib.

Two rules that matter more than anything in this file:

  1. Keep it re-runnable from the ORIGINAL inputs. Patch this script and re-run;
     never hand-edit the output. You will run it dozens of times.
  2. Rewrite references BEFORE merging harvested objects into the target
     datasource, so the rewriter never sees the target's own native field names.
"""
import copy
import re
import xml.etree.ElementTree as ET
from collections import Counter

import twblib as T

# ===================================================================== CONFIG

SOURCE_WB = 'legacy.twb'        # holds the vizes worth keeping
TARGET_WB = 'newmodel.twb'      # holds the datasource to port onto
OUT_WB    = 'ported.twb'

OLD_DS = ['federated.<legacy-a>', 'federated.<legacy-b>']
NEW_DS = 'federated.<target>'

# Legacy table qualifiers to strip before mapping, as a regex alternation.
LEGACY_TABLES = r'LEGACY\.SCHEMA[^)]*|Extract'

# old identifier -> new identifier. VERIFY every target exists (see below).
FIELD_MAP = {
    # 'OLD_FIELD': 'new_field',
    # a name that only exists table-qualified must be mapped that way:
    # 'OLD_CODE': 'new_code (dim_table)',
}

# Workbook objects to drop (e.g. depending on fields with no counterpart).
DROP_CALCS  = set()
DROP_SHEETS = set()
DROP_DASH   = set()

# Data-value translation, applied across all six literal contexts.
VOCABULARY = {
    # 'OLD VALUE': 'New Value',
}

report = Counter()

# ================================================================== HELPERS

def categorical_filter(column, level, members, filter_group=None, context=False):
    """Build a categorical filter with the correct nesting.

    `column`/`level` forms differ by where the filter lives:
        datasource-level -> plain column      '[retailer]'
        worksheet        -> qualified instance '[federated.<id>].[none:retailer:nk]'

    <filter> is (min?, max?, groupfilter, preset?, target*): exactly ONE
    groupfilter. Several members nest inside a function="union" wrapper.
    """
    filt = ET.Element('filter')
    filt.set('class', 'categorical')
    filt.set('column', column)
    if filter_group:
        filt.set('filter-group', filter_group)
    if context:                     # evaluate before Top-N sets and FIXED LODs
        filt.set('context', 'true')

    def member(parent, value):
        gf = ET.SubElement(parent, 'groupfilter')
        gf.set('function', 'member')
        gf.set('level', level)
        gf.set('member', '"%s"' % value)
        return gf

    if len(members) == 1:
        node = member(filt, members[0])
    else:
        node = ET.SubElement(filt, 'groupfilter')
        node.set('function', 'union')
        for value in members:
            member(node, value)
    node.set(T.UI + 'ui-domain', 'database')
    node.set(T.UI + 'ui-enumeration', 'inclusive')
    node.set(T.UI + 'ui-marker', 'enumerate')
    return filt


# ================================================================== 1. LOAD

src_tree, src = T.load(SOURCE_WB)
tgt_tree, tgt = T.load(TARGET_WB)

target_ds = next(d for d in T.datasources(tgt) if d.get('name') == NEW_DS)
target_ds = copy.deepcopy(target_ds)
target_names = T.defined_names(target_ds)

# Sanity-check the map mechanically. A map you only eyeballed is not verified.
missing = {k: v for k, v in FIELD_MAP.items()
           if re.sub(r' \([^)]*\)$', '', v) not in target_names and v not in target_names}
if missing:
    raise SystemExit('FIELD_MAP targets not present in the target datasource: %s' % missing)

# ============================================================== 2. HARVEST

harvested_cols, harvested_sets, harvested_paths = {}, {}, []
for ds_name in OLD_DS:                      # later entries lose name collisions
    ds = next(d for d in T.datasources(src) if d.get('name') == ds_name)
    for col in ds.findall('column'):
        name = (col.get('name') or '').strip('[]')
        if name in DROP_CALCS:
            report['dropped_calc'] += 1
            continue
        # ANY calculation class - filtering on 'tableau' drops grouped dimensions
        if col.find('calculation') is None and col.find('aliases') is None:
            continue
        if name in harvested_cols:
            report['name_collision'] += 1
            continue
        harvested_cols[name] = copy.deepcopy(col)
    for grp in ds.findall('group'):
        harvested_sets.setdefault(grp.get('name'), copy.deepcopy(grp))
    for container in ds.findall('drill-paths'):     # NOT a direct child
        harvested_paths.extend(copy.deepcopy(dp) for dp in container.findall('drill-path'))

# ================================================= 3. STRUCTURAL DELETIONS

for section, drop in (('worksheets', DROP_SHEETS), ('dashboards', DROP_DASH)):
    node = src.find(section)
    for el in list(node) if node is not None else []:
        if el.get('name') in drop:
            node.remove(el); report['dropped_' + section] += 1

for tag in ('datasource-relationships',      # the blend
            'repository-location'):          # server provenance
    el = src.find(tag)
    if el is not None:
        src.remove(el); report['removed_' + tag] += 1

# Preserve shared-views: they also hold single-source workbook-wide filters.
# The rewriter below updates their references; inspect/remove only obsolete blend
# entries. This skeleton assumes a full blend collapse. For a partial migration,
# scope relationship/override deletion to the affected blend as well.

# Third piece of blend state, nested inside every worksheet. Missing it yields a
# workbook that opens and renders fine but fails on EXTRACT creation.
_parents = {c: p for p in src.iter() for c in p}
for el in list(src.iter('join-lod-include-overrides')):
    _parents[el].remove(el); report['removed_join_lod_overrides'] += 1

dss = src.find('datasources')
for ds_name in OLD_DS:
    dss.remove(next(d for d in dss.findall('datasource') if d.get('name') == ds_name))

# ============================================ 4. REWRITE (before merging!)

rewrite_text, rewrite_tree = T.make_rewriter(
    FIELD_MAP, {old: NEW_DS for old in OLD_DS}, legacy_table_pattern=LEGACY_TABLES)

report.update(rewrite_tree(src))
for frag in list(harvested_cols.values()) + list(harvested_sets.values()) + harvested_paths:
    rewrite_tree(frag)

# ===================================================== 5. SEMANTIC FIXES

# Replace hand-built logic the new model provides natively, collapse conditionals
# the new model makes unnecessary, and add helper calcs reproducing any old
# ENCODING (padding / separators / composite keys) the new fields spell
# differently. Verify each against the warehouse before trusting it.

# ========================================================== 6. MERGE

existing = {c.get('name') for c in target_ds.findall('column')}
by_name = {c.get('name'): c for c in target_ds.findall('column')}
for name, col in harvested_cols.items():
    if col.get('name') in existing:
        # a physical column that already exists: keep its display metadata
        aliases = col.find('aliases')
        if aliases is not None and by_name[col.get('name')].find('aliases') is None:
            by_name[col.get('name')].append(copy.deepcopy(aliases))
        continue
    target_ds.append(col); report['calcs_merged'] += 1
for grp in harvested_sets.values():
    target_ds.append(grp)
if harvested_paths:
    container = target_ds.find('drill-paths') or ET.SubElement(target_ds, 'drill-paths')
    for dp in harvested_paths:
        container.append(dp)
dss.append(target_ds)

# Collapse the now-duplicated per-worksheet dependency blocks.
for parent in {p for p in src.iter() for c in p if c.tag == 'datasource-dependencies'}:
    seen = {}
    for dep in [c for c in list(parent) if c.tag == 'datasource-dependencies']:
        key = dep.get('datasource')
        if key in seen:
            have = {(c.tag, c.get('name')) for c in seen[key]}
            for child in list(dep):
                if (child.tag, child.get('name')) not in have:
                    seen[key].append(child)
            parent.remove(dep); report['dep_blocks_merged'] += 1
        else:
            seen[key] = dep

# ============================================ 7. LEGALITY + VOCABULARY

report['self_qualifiers_stripped'] = T.strip_self_qualifiers(src, NEW_DS)

if VOCABULARY:
    pat = re.compile(r'''(['"])(%s)\1''' %
                     '|'.join(re.escape(k) for k in sorted(VOCABULARY, key=len, reverse=True)))
    for ctx, sites in T.literal_sites(src).items():
        for value, setter in sites:
            new = pat.sub(lambda m: m.group(1) + VOCABULARY[m.group(2)] + m.group(1), value)
            if new != value:
                setter(new); report['vocab_' + ctx.replace('/', '_')] += 1

# Parameters are duplicated into every worksheet's dependency block; re-sync them
# after retargeting any domain, or stale copies linger.
params = T.parameters_ds(src)
if params is not None:
    authoritative = {c.get('name'): c for c in params.findall('column')}
    for dep in src.iter('datasource-dependencies'):
        if dep.get('datasource') != 'Parameters':
            continue
        for col in list(dep.findall('column')):
            fresh = authoritative.get(col.get('name'))
            if fresh is not None and ET.tostring(fresh) != ET.tostring(col):
                dep.remove(col); dep.append(copy.deepcopy(fresh))
                report['param_decls_synced'] += 1

# ================================================== 8. ORDER + WRITE

report['datasources_reordered'] = T.enforce_child_order(src)
T.save(src_tree, OUT_WB)

for key, val in sorted(report.items()):
    print('  %-30s %s' % (key, val))
print('\nwrote %s' % OUT_WB)
print('now run: twb_validate.py %s --compare %s %s' % (OUT_WB, SOURCE_WB, TARGET_WB))
