#!/usr/bin/env python3
"""Validation ladder for a ported .twb. Each layer catches a different class.

    uv run --no-project python twb_validate.py PORTED.twb \
        [--compare SOURCE.twb ...] [--stale OLD_ID ...] [-v]

Exit code is the number of layers that failed, so it drops into CI.

Layers 1-6 only. Layer 7 (vocabulary) is twb_vocab.py; layer 8 (semantics) means
querying the warehouse and cannot be automated here - and it is the only layer
that catches wrong *numbers*. Never report a port as verified on structure alone.
"""
import argparse, html, itertools, re, sys
from collections import Counter, defaultdict
import twblib as T

BUILTIN_REFS = {'Multiple Values', 'Measure Names', 'Measure Values', ':Measure Names'}


def _defined(root):
    names = set()
    for ds in T.datasources(root):
        names |= T.defined_names(ds)
    names |= T.local_definitions(root)
    names |= {re.sub(r' \([^)]*\)$', '', n) for n in names}
    # Tableau's declarations are authoritative for stacked derivations and
    # virtual totals: pcto:usr:X:qk and usr:X:vtsum:qk both point to column X.
    # Accept the instance spelling only if its underlying column resolves.
    for instance in root.iter('column-instance'):
        column = T.ref_base((instance.get('column') or '').strip('[]'))
        if column in names:
            names.add(T.ref_base((instance.get('name') or '').strip('[]')))
    return names


# Element content models Tableau enforces beyond <datasource> child order.
# {parent tag: (child tag, max occurrences)}
CHILD_LIMITS = {
    # <filter> is (min?, max?, groupfilter, preset?, target*) - at most ONE
    # groupfilter. Several members must be nested inside a single
    # function="union" groupfilter, not emitted as siblings.
    'filter': ('groupfilter', 1),
}


def layer1_loads(root, v):
    """Known schema child-order/content constraints, not the full Tableau schema."""
    bad, content_ok = [], True
    for parent_tag, (child_tag, limit) in CHILD_LIMITS.items():
        for el in root.iter(parent_tag):
            n = len(el.findall(child_tag))
            if n > limit:
                print('    <%s> has %d direct <%s> children (max %d): %s'
                      % (parent_tag, n, child_tag, limit,
                         (el.get('column') or '')[-52:]))
                content_ok = False
    # Omitting slices is legal, but a present slices element is (column+).
    # Removing a view's last filter must not leave <slices/> behind.
    for slices in root.iter('slices'):
        if not len(slices) or any(child.tag != 'column' for child in slices):
            print('    <slices> requires one or more <column> children')
            content_ok = False
    # Encoding maps require exactly one bucket or multibucket. Removing a
    # retired category's bucket must remove its enclosing map as well.
    # Other <map> contexts (e.g. connection cols) have different content models.
    for encoding in root.iter('encoding'):
        for mapping in encoding.findall('map'):
            tags = [child.tag for child in mapping]
            if tags not in (['bucket'], ['multibucket']):
                print('    encoding <map> requires one <bucket> or <multibucket>: %s'
                      % (encoding.get('field') or ''))
                content_ok = False
    rank = {t: i for i, t in enumerate(T.DS_CHILD_ORDER)}
    for ds in T.datasources(root):
        tags = [c.tag for c in ds]
        ranks = [rank.get(t, len(T.DS_CHILD_ORDER)) for t in tags]
        if ranks != sorted(ranks):
            bad.append((ds.get('caption') or ds.get('name'), tags))
    for name, tags in bad:
        print('    OUT OF ORDER in %r: %s' % (name, tags))
    return not bad and content_ok


def layer2_resolve(root, v):
    """Every reference names something defined. Comments stripped first."""
    known = _defined(root)
    unresolved = Counter()
    for calc in root.iter('calculation'):
        for base in T.refs_in(calc.get('formula'), live_only=True):
            if base in BUILTIN_REFS or base == 'Parameters' or base.startswith('federated.'):
                continue
            if base not in known and re.sub(r' \([^)]*\)$', '', base) not in known:
                unresolved[base] += 1
        col = calc.get('column')
        if col:
            b = T.ref_base(col.strip('[]'))
            if b not in known:
                unresolved['<bin source> ' + b] += 1
    for section in ('worksheets', 'dashboards'):
        node = root.find(section)
        if node is None:
            continue
        for m in T.QUALIFIED.finditer(html.unescape(__import__('xml.etree.ElementTree',
                                                 fromlist=['tostring']).tostring(node, encoding='unicode'))):
            base = T.ref_base(m.group(2))
            if base in BUILTIN_REFS:
                continue
            if base not in known and re.sub(r' \([^)]*\)$', '', base) not in known:
                unresolved[base] += 1
    for k, n in unresolved.most_common(20 if not v else 200):
        print('    unresolved x%-4d %s' % (n, k))
    return not unresolved


def layer3_legal(root, v):
    """Resolution is not legality. After collapsing a blend, references naming
    the surviving datasource from inside its own calcs are invalid."""
    qualifiers = Counter()
    for calc in root.iter('calculation'):
        for m in re.finditer(r'\[([^\[\]]+)\]\s*\.\s*\[', T.strip_comments(calc.get('formula') or '')):
            qualifiers[m.group(1)] += 1
    illegal = {k: n for k, n in qualifiers.items() if k != 'Parameters'}
    for k, n in illegal.items():
        print('    self/foreign qualifier in formulas x%-4d [%s]' % (n, k))

    # Qualification is context-dependent. A DATASOURCE-level filter must name its
    # column UNqualified - Tableau supplies the datasource context, so a qualified
    # reference becomes [ds].[ds].[field] and warns "field does not exist".
    # Worksheet filters are the opposite: there the qualifier is required.
    for ds in T.datasources(root):
        for filt in ds.findall('filter'):
            col = filt.get('column') or ''
            if col.startswith('[federated.') or ':' in col:
                print('    datasource filter should name the plain column '
                      '(e.g. [retailer]), got: %s' % col)
                illegal['<ds filter>'] = illegal.get('<ds filter>', 0) + 1
    for ws in T.worksheets(root):
        view = ws.find('.//view')
        for filt in (view.findall('filter') if view is not None else []):
            col = filt.get('column') or ''
            if col and not col.startswith('[federated.') and not col.startswith('[Parameters]'):
                print('    worksheet filter column is bare (should be qualified) in %r: %s'
                      % (ws.get('name'), col))
                illegal['<ws filter>'] = illegal.get('<ws filter>', 0) + 1
    if v:
        print('    (legitimate) [Parameters] x%d' % qualifiers.get('Parameters', 0))
    groups_ok = _categorical_group_references(root)
    return not illegal and groups_ok


def _scoped_elements(root, datasource=None):
    """Carry definition scope without confusing equal names in different sources."""
    if root.tag == 'datasource':
        datasource = root.get('name', datasource)
    elif root.tag == 'datasource-dependencies':
        datasource = root.get('datasource', datasource)
    yield root, datasource
    for child in root:
        yield from _scoped_elements(child, datasource)


def _categorical_group_references(root):
    """A categorical-bin group uses a direct reference, not none:Group:nk.

    Base-name resolution accepts that invalid wrapper; Desktop rejects it with
    9CA7205B. Limit this guard to the observed wrapper and the correct datasource.
    """
    groups = defaultdict(set)
    for element, datasource in _scoped_elements(root):
        if (element.tag == 'column' and datasource and
                element.find('calculation[@class="categorical-bin"]') is not None):
            groups[datasource].add(T.ref_base((element.get('name') or '').strip('[]')))
    bad = Counter()

    def check(inner, datasource):
        match = T.DERIV.fullmatch(inner)
        if (match and match.group(1) == 'none' and match.group(3) == 'nk'
                and T.ref_base(inner) in groups.get(datasource, set())):
            bad[(datasource, inner)] += 1

    for element, datasource in _scoped_elements(root):
        values = [T.strip_comments(value) if key == 'formula' else value
                  for key, value in element.attrib.items()]
        values.append(element.text or '')
        for value in values:
            for match in T.QUALIFIED.finditer(value):
                check(match.group(2), match.group(1))
            # Do not re-check a foreign qualified field using the enclosing scope.
            unqualified = T.QUALIFIED.sub('', value)
            for inner in re.findall(r'\[([^\[\]]+)\]', unqualified):
                check(inner, datasource)
    for (datasource, inner), count in bad.items():
        print('    categorical-bin group requires a direct reference x%d [%s].[%s]'
              % (count, datasource, inner))
    return not bad


def layer4_stale(root, stale, v):
    """Old datasource ids, captions and source-system table names must be gone."""
    if not stale:
        print('    (no --stale identifiers given, skipped)')
        return True
    blob = __import__('xml.etree.ElementTree', fromlist=['tostring']).tostring(root, encoding='unicode')
    hits = {s: blob.count(s) for s in stale}
    for s, n in hits.items():
        print('    %-46s %d' % (s, n))
    return not any(hits.values())


# Blend state lives in three places. Two are workbook-level and obvious; the third
# hides inside worksheets and survives a naive collapse, only failing at EXTRACT
# time with "the field X is not from the worksheet's data source".
BLEND_ELEMENTS = ('datasource-relationships', 'shared-views',
                  'join-lod-include-overrides')


def layer5_structure(root, v):
    """Zones name real worksheets; no orphan windows; no duplicate definitions;
    no blend leftovers when only one real datasource remains."""
    ok = True
    real = [d for d in T.datasources(root) if d.get('name') != 'Parameters']
    if len(real) < 2:
        for tag in BLEND_ELEMENTS:
            if tag == 'shared-views':
                # A single-source shared view also stores workbook-wide filters.
                # Preserve these; their presence alone does not imply a blend.
                for view in root.findall('./shared-views/shared-view'):
                    sources = {d.get('name') for d in view.findall('./datasources/datasource')}
                    if not sources <= {d.get('name') for d in T.datasources(root)}:
                        print('    shared view references a missing datasource: %s' % sources)
                        ok = False
                continue
            n = sum(1 for _ in root.iter(tag))
            if n:
                print('    %d <%s> left over: blend state, but only %d real '
                      'datasource(s). Fails on extract creation.' % (n, tag, len(real)))
                ok = False
    sheets = {w.get('name') for w in T.worksheets(root)}
    dashes = {d.get('name') for d in T.dashboards(root)}
    for w in T.worksheets(root):
        # The first datasource listed in a worksheet is its PRIMARY. Parameters there
        # makes Desktop remove the sheet: "does not have a valid data source".
        first = w.find('./table/view/datasources/datasource')
        if first is not None and first.get('name') == 'Parameters':
            print('    worksheet %r lists Parameters as its primary datasource' % w.get('name'))
            ok = False
    for db in T.dashboards(root):
        for z in db.iter('zone'):
            n = z.get('name')
            if n and z.get('type-v2') is None and n not in sheets:
                print('    dashboard %r zone names missing worksheet %r' % (db.get('name'), n))
                ok = False
    wins = root.find('windows')
    if wins is not None:
        for w in wins.findall('window'):
            if w.get('class') == 'worksheet' and w.get('name') not in sheets:
                print('    orphan worksheet window %r' % w.get('name')); ok = False
            if w.get('class') == 'dashboard' and w.get('name') not in dashes:
                print('    orphan dashboard window %r' % w.get('name')); ok = False
    for dep in root.iter('datasource-dependencies'):
        seen = Counter((c.tag, c.get('name')) for c in dep)
        for key, n in seen.items():
            if n > 1:
                print('    duplicate %s in a dependency block' % (key,)); ok = False
    # Set controls must resolve in their own datasource; a same-named set in
    # another source cannot satisfy the param reference.
    sets = {ds.get('name'): {T.ref_base((g.get('name') or '').strip('[]'))
                            for g in ds.findall('group')}
            for ds in T.datasources(root)}
    for element in root.iter():
        is_card = element.tag == 'card' and element.get('type') == 'setMembership'
        is_zone = element.tag == 'zone' and element.get('type-v2') == 'setMembership'
        if not (is_card or is_zone):
            continue
        param = element.get('param') or ''
        match = re.fullmatch(r'\[([^\[\]]+)\]\.\[([^\[\]]+)\]', param)
        if (not match or T.DERIV.fullmatch(match.group(2)) or
                T.ref_base(match.group(2)) not in sets.get(match.group(1), set())):
            print('    set control param does not name a direct set in its datasource: %s' % param)
            ok = False
        if is_zone and element.get('name') not in sheets:
            print('    set control zone names missing worksheet %r' % element.get('name'))
            ok = False
    return ok


def layer6_order(root, sources, v):
    """Diff parent/child tag sequences against the source workbooks. Patterns in
    neither input are where corruption hides - though most hits are benign."""
    if not sources:
        print('    (no --compare workbooks given, skipped)')
        return True

    def patterns(r):
        pat = defaultdict(set)
        for parent in r.iter():
            seq = tuple(k for k, _ in itertools.groupby(c.tag for c in parent))
            if seq:
                pat[parent.tag].add(seq)
        return pat

    known = defaultdict(set)
    for src in sources:
        for k, val in patterns(T.load(src)[1]).items():
            known[k] |= val
    novel = [(tag, seq) for tag, seqs in patterns(root).items()
             for seq in seqs if seq not in known.get(tag, set())]
    for tag, seq in novel:
        print('    novel child order under <%s>: %s' % (tag, seq))
    if novel:
        print('    NOTE: benign if a subsequence of a source (deletions) or a new'
              '\n          combination of optional elements. Read each one.')
    return True     # advisory, never fails the run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('workbook')
    ap.add_argument('--compare', nargs='*', default=[], help='source workbooks for layer 6')
    ap.add_argument('--stale', nargs='*', default=[], help='identifiers that must be gone')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()

    _, root = T.load(a.workbook)
    layers = [
        ('1  loads (schema child order)', lambda: layer1_loads(root, a.verbose)),
        ('2  references resolve',         lambda: layer2_resolve(root, a.verbose)),
        ('3  references are legal',       lambda: layer3_legal(root, a.verbose)),
        ('4  no stale identifiers',       lambda: layer4_stale(root, a.stale, a.verbose)),
        ('5  structural integrity',       lambda: layer5_structure(root, a.verbose)),
        ('6  order-pattern diff',         lambda: layer6_order(root, a.compare, a.verbose)),
    ]
    failed = 0
    for label, fn in layers:
        print('\nLAYER %s' % label)
        if not fn():
            failed += 1
            print('    -> FAIL')
        else:
            print('    -> ok')
    print('\n%d worksheets, %d dashboards, %d datasources' %
          (len(T.worksheets(root)), len(T.dashboards(root)), len(T.datasources(root))))
    print('%s' % ('ALL LAYERS PASSED' if not failed else '%d LAYER(S) FAILED' % failed))
    print('NOT CHECKED HERE: full Desktop schema/type inference, vocabulary '
          '(twb_vocab.py), numerical semantics, rendering, or refresh/publish.')
    return failed


if __name__ == '__main__':
    sys.exit(main())
