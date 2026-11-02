"""Shared helpers for reading and transforming Tableau .twb workbooks.

Pure stdlib. Import from the CLI tools in this directory, or from a port script.

A .twb is plain XML. The two things that make it awkward:
  * field references appear in several syntaxes, with wrappers and escaping
  * <datasource> children must obey a fixed schema order or the file won't open
"""
import copy
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

UNS = 'http://www.tableausoftware.com/xml/user'
UI = '{%s}' % UNS
ET.register_namespace('user', UNS)

# ---------------------------------------------------------------- load / save

def load(path):
    """Parse a workbook. Returns (tree, root)."""
    tree = ET.parse(path)
    return tree, tree.getroot()


def save(tree, path):
    tree.write(path, encoding='utf-8', xml_declaration=True)


def signature(el):
    """Structural fingerprint, for round-trip comparison."""
    return (el.tag, tuple(sorted(el.attrib.items())),
            (el.text or '').strip(), tuple(signature(c) for c in el))


def roundtrip_ok(path, tmp_path):
    """Validation layer 0: does this library preserve the document structurally?"""
    tree, root = load(path)
    save(tree, tmp_path)
    return signature(root) == signature(load(tmp_path)[1])


# ---------------------------------------------------------------- navigation

def datasources(root):
    node = root.find('datasources')
    return [] if node is None else node.findall('datasource')


def real_datasources(root):
    """Datasources backed by data, i.e. excluding the Parameters pseudo-datasource."""
    return [d for d in datasources(root) if d.get('name') != 'Parameters']


def parameters_ds(root):
    return next((d for d in datasources(root) if d.get('name') == 'Parameters'), None)


def worksheets(root):
    node = root.find('worksheets')
    return [] if node is None else node.findall('worksheet')


def dashboards(root):
    node = root.find('dashboards')
    return [] if node is None else node.findall('dashboard')


def parent_map(root):
    return {child: parent for parent in root.iter() for child in parent}


# ---------------------------------------------------------------- references

DERIV = re.compile(r'^([A-Za-z][A-Za-z0-9_]*):(.+?):([a-z]{2})(:\d+)?$')
# Instance wrappers can STACK and carry a visual-totals token:
#   [pcto:cum:usr:Calc:qk]  [usr:Calc:vtnone:qk]  [none:Calc:nk:1]
# DERIV alone sees 'pcto' + 'cum:usr:Calc', so a field map keyed by 'Calc' silently misses.
DERIV_TOKENS = {
    'none', 'sum', 'avg', 'min', 'max', 'cnt', 'cntd', 'ctd', 'attr', 'med', 'usr', 'agg',
    'stdev', 'stdevp', 'var', 'varp', 'pctl', 'io', 'yr', 'qr', 'mn', 'wk', 'dy', 'wd', 'hr',
    'mi', 'sc', 'my', 'tyr', 'tqr', 'tmn', 'twk', 'tdy', 'thr', 'tmi', 'tsc', 'pcto', 'pcdf',
    'diff', 'cum', 'rank', 'rnk', 'mavg', 'pctrank', 'run', 'win',
}
INSTANCE_SUFFIX = re.compile(r'((?::(?:vtnone|vtcum|vtavg|vtsum|vtmin|vtmax))?:[a-z]{2}(?::\d+)?)$')
BRACKET = re.compile(r'\[([^\[\]]*)\]')
QUALIFIED = re.compile(r'\[(federated\.[A-Za-z0-9]+|Parameters)\]\s*\.\s*\[([^\[\]]+)\]')
TABLE_QUALIFIER = re.compile(r' \([^)]*\)$')


def unescape(name):
    """Tableau escapes # and % inside bracketed identifiers."""
    return name.replace('\\#', '#').replace('\\%', '%')


def split_reference(inner, known_names=None):
    """Split a bracketed token into (prefix, base, suffix).

    'pcto:cum:usr:My Calc:qk' -> ('pcto:cum:usr:', 'My Calc', ':qk').

    With `known_names`, the base is the longest known name bounded by ':' or the token
    edge. Prefer this: field names can themselves contain ':' ('day:sunday units'), and
    lowercase physical names ('retailer', 'date') look like derivation tokens to any
    parser. Without it, a stacked chain of known derivation tokens and a type suffix are
    stripped. Returns None when known_names is given and nothing matches.
    """
    u = unescape(inner)
    if known_names is not None:
        best = None
        for name in known_names:
            for m in re.finditer(re.escape(name), u):
                s, e = m.start(), m.end()
                if (s == 0 or u[s - 1] == ':') and (e == len(u) or u[e] == ':'):
                    if best is None or len(name) > len(best[1]):
                        best = (u[:s], name, u[e:])
        return best
    m = INSTANCE_SUFFIX.search(u)
    if not m or ':' not in u[:m.start()]:
        return ('', u, '')
    body, suffix = u[:m.start()], m.group(1)
    parts = body.split(':')
    i = 0
    while i < len(parts) - 1 and parts[i] in DERIV_TOKENS:
        i += 1
    if i == 0:
        return ('', u, '')
    return (':'.join(parts[:i]) + ':', ':'.join(parts[i:]), suffix)


def ref_base(inner, known_names=None):
    """Strip derivation wrappers, including stacked ones and :vtnone-style tokens."""
    parts = split_reference(inner, known_names)
    return parts[1] if parts else unescape(inner)


def strip_comments(formula):
    """Remove // and /* */ comments. Real workbooks are full of dead references."""
    if not formula:
        return ''
    formula = re.sub(r'/\*.*?\*/', '', formula, flags=re.S)
    return '\n'.join(re.sub(r'//.*$', '', line) for line in formula.split('\n'))


def refs_in(text, live_only=False):
    """Every bracketed identifier in a string, as base names."""
    if not text:
        return []
    if live_only:
        text = strip_comments(text)
    return [ref_base(m.group(1)) for m in BRACKET.finditer(text)]


# ---------------------------------------------------------------- definitions

def defined_names(ds):
    """Every object a datasource defines: columns, sets, hierarchies, instances."""
    names = set()
    for tag in ('column', 'group', 'drill-path', 'column-instance'):
        for el in ds.findall(tag):
            n = el.get('name')
            if n:
                names.add(n.strip('[]'))
    for container in ds.findall('drill-paths'):
        for dp in container.findall('drill-path'):
            if dp.get('name'):
                names.add(dp.get('name').strip('[]'))
    return names


def local_definitions(root):
    """Calcs declared inside worksheet dependency blocks. Legal, and easy to miss:
    a resolver that only looks at datasource level reports these as unresolved."""
    names = set()
    for dep in root.iter('datasource-dependencies'):
        for col in dep.findall('column'):
            if col.get('name'):
                names.add(col.get('name').strip('[]'))
    return names


def calculations(ds):
    """{name: (caption, calculation element)} for every workbook-defined column.

    Note the ANY-class test. Grouped dimensions use class='categorical-bin' and
    carry their logic in child <bin> elements, not in @formula. Filtering on
    class='tableau' silently drops every one of them.
    """
    out = {}
    for col in ds.findall('column'):
        calc = col.find('calculation')
        if calc is not None:
            out[(col.get('name') or '').strip('[]')] = (col.get('caption'), calc)
    return out


def physical_columns(ds):
    """Remote (warehouse) column names, from metadata records."""
    names = set()
    for rec in ds.findall(".//metadata-record[@class='column']"):
        remote = rec.find('remote-name')
        if remote is not None and remote.text:
            names.add(remote.text)
    return names


def column_provenance(ds):
    """{table: column count} - which related table each field comes from."""
    counts = Counter()
    for rec in ds.findall(".//metadata-record[@class='column']"):
        parent = rec.find('parent-name')
        if parent is not None and parent.text:
            counts[parent.text.strip('[]')] += 1
    return counts


# ---------------------------------------------------------------- architecture

def architecture(root, ds):
    """How is this datasource assembled? Drives whether a port is viable."""
    facts = {}
    facts['has_blend'] = root.find('datasource-relationships') is not None
    facts['relationships'] = len(ds.findall('.//object-graph//relationship'))
    facts['objects'] = [o.get('caption') for o in ds.findall('.//object-graph//object')]
    facts['custom_sql'] = [r.get('name') for r in ds.findall('.//relation[@type="text"]')]
    facts['tables'] = sorted({r.get('table') for r in ds.findall('.//relation[@type="table"]')
                              if r.get('table')})
    facts['has_extract'] = ds.find('extract') is not None
    return facts


def shared_view_filters(root):
    """Workbook-wide filters ("apply to all worksheets using this data source").

    They live in <shared-views>, NOT in any worksheet's <filter> list: a sheet joins
    them only through a <slices> entry and dependency declarations. A per-sheet survey
    therefore misses them - e.g. a segment = "Core" scope that makes a datasource
    look 30-40% bigger than the dashboards actually show.
    Returns [(datasource, column, context, members)].
    """
    out = []
    sv = root.find('shared-views')
    if sv is None:
        return out
    for view in sv.findall('shared-view'):
        for f in view.findall('filter'):
            members = [g.get('member') for g in f.iter('groupfilter') if g.get('member')]
            fn = f.find('groupfilter')
            out.append((view.get('name'), f.get('column'), f.get('context') == 'true',
                        members or ([fn.get('function')] if fn is not None else [])))
    return out


def blend_links(root):
    """The blend's column-mapping is ground truth for semantic equivalence:
    two fields linked to each other mean the same thing, whatever they're called."""
    rel = root.find('datasource-relationships')
    if rel is None:
        return []
    return [(m.get('key'), m.get('value'))
            for m in rel.findall('.//column-mapping/map')]


# ---------------------------------------------------------------- rewriting

def make_rewriter(field_map, ds_map, legacy_table_pattern=None, known_names=None):
    r"""Build a reference rewriter.

    field_map            : {old base name -> new base name}
    ds_map               : {old datasource id -> new datasource id}
    legacy_table_pattern : optional regex matching legacy table qualifiers, e.g.
                           r'LEGACY\.SCHEMA[^)]*|Extract'.  A qualifier that
                           matches is stripped before lookup, so
                           `[FIELD (Legacy Table)]` maps via `FIELD`.

    known_names          : optional iterable of every legacy field name. Strongly
                           recommended: wrappers are then resolved against real names, so
                           stacked derivations, ':vtnone' tokens and names containing ':'
                           all map. Without it, a built-in token list is used.

    Only bracket *contents* are touched, so string literals in formulas are safe.
    Derivation wrappers and table-calc suffixes are preserved.  Unmapped names are
    returned verbatim, keeping Tableau's \# / \% escaping intact.
    """
    known = None
    if known_names is not None:
        known = sorted(set(known_names), key=len, reverse=True)
    strip_re = (re.compile(r'^(.*?) \((?:%s)\)$' % legacy_table_pattern)
                if legacy_table_pattern else None)

    def remap_base(base):
        key = unescape(base)
        if strip_re:
            m = strip_re.match(key)
            if m:
                key = m.group(1)
        return field_map.get(key, base)          # verbatim when unmapped

    def remap_inner(inner):
        if inner in ds_map:
            return ds_map[inner]
        parts = split_reference(inner, known)
        if not parts or not parts[0]:
            return remap_base(inner)
        prefix, base, suffix = parts
        new = remap_base(base)
        if new == base:                          # unmapped: keep the original escaping
            return inner
        return prefix + new + suffix

    def rewrite_text(text):
        if not text or '[' not in text:
            return text
        return BRACKET.sub(lambda m: '[' + remap_inner(m.group(1)) + ']', text)

    def rewrite_tree(el, counter=None):
        counter = Counter() if counter is None else counter
        for key, val in list(el.attrib.items()):
            if key in ('datasource', 'name') and val in ds_map:
                el.set(key, ds_map[val])
                counter['datasource_ids'] += 1
                continue
            new = rewrite_text(val)
            if new != val:
                el.set(key, new)
                counter['attributes'] += 1
        if el.text:
            new = rewrite_text(el.text)
            if new != el.text:
                el.text = new
                counter['text'] += 1
        for child in el:
            rewrite_tree(child, counter)
        return counter

    return rewrite_text, rewrite_tree


def strip_self_qualifiers(root, ds_name):
    """`[federated.X].[field]` is legal ONLY when X is a DIFFERENT datasource.

    Collapse a blend into one datasource and those references become
    self-qualified; Tableau marks the calculation invalid (red pill, blank viz)
    without raising an error. Formulas only - the qualified form is required in
    worksheet XML.
    """
    pattern = re.compile(r'\[' + re.escape(ds_name) + r'\]\s*\.\s*')
    stripped = 0
    for calc in root.iter('calculation'):
        formula = calc.get('formula')
        if formula and ds_name in formula:
            new, n = pattern.subn('', formula)
            if n:
                calc.set('formula', new)
                stripped += n
    return stripped


# ---------------------------------------------------------------- schema order

DS_CHILD_ORDER = [
    'repository-location', 'connection', 'utility-dimensions', 'dimension',
    'overridable-settings', 'aliases', 'column', 'column-instance', 'group',
    'mapped-images', 'drill-paths', 'unlinked-server-hierarchies',
    'folders-common', 'folders-parameters', 'actions', 'calculated-members',
    'extract', 'layout', 'style', 'semantic-values', 'date-options',
    'default-date-format', 'default-sorts', 'field-sort-info',
    'datasource-dependencies', 'explainability', 'filter', 'object-graph',
]
_RANK = {tag: i for i, tag in enumerate(DS_CHILD_ORDER)}


def enforce_child_order(root):
    """Tableau validates <datasource> against a fixed content model. Appended
    elements left at the end make the workbook refuse to open (Error D2E8DA72).
    Stable sort, so relative order of same-tag siblings is preserved."""
    fixed = 0
    for ds in datasources(root):
        kids = list(ds)
        ordered = sorted(kids, key=lambda e: _RANK.get(e.tag, len(DS_CHILD_ORDER)))
        if [id(x) for x in kids] != [id(x) for x in ordered]:
            for k in kids:
                ds.remove(k)
            for k in ordered:
                ds.append(k)
            fixed += 1
    return fixed


# ---------------------------------------------------------------- data literals

def literal_sites(root):
    """Every place a *data value* can hide. Missing any one fails silently.

    Returns {context: [(value, setter)]} where setter(new_value) writes it back,
    so a caller can reconcile vocabulary without knowing the XML.
    """
    sites = defaultdict(list)

    def add(ctx, value, setter):
        if value:
            sites[ctx].append((value, setter))

    for calc in root.iter('calculation'):
        f = calc.get('formula')
        add('formula', f, lambda v, c=calc: c.set('formula', v))

    for gf in root.iter('groupfilter'):
        add('filter/set member', gf.get('member'),
            lambda v, g=gf: g.set('member', v))

    for b in root.iter('bin'):
        add('bin label', b.get('value'), lambda v, e=b: e.set('value', v))
        for val in b.findall('value'):
            add('bin member', val.text, lambda v, e=val: setattr(e, 'text', v))

    for mem in root.iter('member'):
        add('parameter domain', mem.get('value'),
            lambda v, m=mem: m.set('value', v))

    for al in root.iter('alias'):
        add('alias key', al.get('key'), lambda v, a=al: a.set('key', v))
        add('alias value', al.get('value'), lambda v, a=al: a.set('value', v))

    for bucket in root.iter('bucket'):
        add('manual sort', bucket.text,
            lambda v, b=bucket: setattr(b, 'text', v))

    return sites


# ---------------------------------------------------------------- sheet names

SHEET_NAME_TAGS = {'worksheet', 'dashboard', 'zone', 'window', 'viewpoint', 'exclude-sheet'}


def rename_sheets(root, mapping):
    """Rename known sheet bindings, including actions and device layouts.

    Mapping keys/values are exact worksheet or dashboard names, not field IDs.
    Preserve captions, formatted text, parameter values outside actions, and
    connection metadata. Audit unfamiliar reference forms separately.
    """
    names = [el.get('name') for el in worksheets(root) + dashboards(root)]
    renamed = [mapping.get(name, name) for name in names]
    if len(renamed) != len(set(renamed)):
        raise ValueError('Sheet renaming would produce duplicate names')

    n = 0

    def rename_attr(el, attr):
        nonlocal n
        old = el.get(attr)
        if old in mapping and mapping[old] != old:
            el.set(attr, mapping[old])
            n += 1

    for el in root.iter():
        if el.tag in SHEET_NAME_TAGS:
            rename_attr(el, 'name')
    for action in root.iter('action'):
        for el in action.iter():
            if el.tag == 'source':
                rename_attr(el, 'worksheet')
                rename_attr(el, 'dashboard')
            elif el.tag == 'param' and el.get('name') == 'target':
                rename_attr(el, 'value')
    return n
