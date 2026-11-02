#!/usr/bin/env python3
"""Inventory a .twb: what's in it, how it's assembled, what it would take to port.

    uv run --no-project python twb_survey.py WORKBOOK.twb [--fields] [--json]

Run this on BOTH workbooks before touching anything. Never start from assumptions
about scale or architecture.
"""
import argparse, json, sys
from collections import Counter
import twblib as T


def survey(path, want_fields=False):
    _, root = T.load(path)
    out = {'workbook': path, 'datasources': [], 'worksheets': len(T.worksheets(root)),
           'dashboards': [d.get('name') for d in T.dashboards(root)]}

    params = T.parameters_ds(root)
    out['parameters'] = len(params.findall('column')) if params is not None else 0

    blend = T.blend_links(root)
    out['blend_linking_fields'] = len(blend)
    if blend:
        out['blend_links'] = [(a.split('].[')[-1].rstrip(']'),
                               b.split('].[')[-1].rstrip(']')) for a, b in blend]

    for ds in T.real_datasources(root):
        arch = T.architecture(root, ds)
        calcs = T.calculations(ds)
        classes = Counter(c.get('class') for _, c in calcs.values())
        entry = {
            'name': ds.get('name'),
            'caption': ds.get('caption'),
            'physical_columns': len(T.physical_columns(ds)),
            'defined_columns': len(ds.findall('column')),
            'calculations': len(calcs),
            'calculation_classes': dict(classes),
            'sets': len(ds.findall('group')),
            'hierarchies': len(ds.findall('.//drill-path')),
            'tables': arch['tables'],
            'relationships': arch['relationships'],
            'custom_sql': arch['custom_sql'],
            'has_extract': arch['has_extract'],
            'provenance': dict(T.column_provenance(ds)),
        }
        if want_fields:
            entry['physical_column_names'] = sorted(T.physical_columns(ds))
        out['datasources'].append(entry)

    out['shared_filters'] = [dict(datasource=d, column=c, context=ctx, members=m)
                             for d, c, ctx, m in T.shared_view_filters(root)]

    out['architecture'] = ('blend' if blend else
                           'relationships' if any(d['relationships'] for d in out['datasources'])
                           else 'single/join')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('workbook')
    ap.add_argument('--fields', action='store_true', help='list physical column names')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    s = survey(a.workbook, a.fields)
    if a.json:
        print(json.dumps(s, indent=1)); return

    print('=' * 68)
    print(s['workbook'])
    print('=' * 68)
    print('architecture : %s' % s['architecture'])
    print('worksheets   : %d' % s['worksheets'])
    print('dashboards   : %d  %s' % (len(s['dashboards']), s['dashboards']))
    print('parameters   : %d' % s['parameters'])
    if s['blend_linking_fields']:
        print('blend        : %d linking fields' % s['blend_linking_fields'])
        for x, y in s.get('blend_links', []):
            print('               %-42s = %s' % (x, y))
    if s['shared_filters']:
        print('shared filters (workbook-wide; not in any sheet\'s own filters):')
        for f in s['shared_filters']:
            print('               %s %s %s' % (f['column'], 'context' if f['context'] else '',
                                              f['members'][:6]))
    for d in s['datasources']:
        print('\n--- datasource %r' % (d['caption'] or d['name']))
        print('    physical columns : %d' % d['physical_columns'])
        print('    calculations     : %d  %s' % (d['calculations'], d['calculation_classes']))
        print('    sets / hierarchies: %d / %d' % (d['sets'], d['hierarchies']))
        if d['relationships']:
            print('    relationships    : %d' % d['relationships'])
        if d['custom_sql']:
            print('    custom SQL       : %s' % d['custom_sql'])
        if d['has_extract']:
            print('    extract          : yes')
        if d['provenance']:
            print('    columns by table :')
            for t, n in sorted(d['provenance'].items(), key=lambda x: -x[1]):
                print('        %-34s %d' % (t, n))
        if 'physical_column_names' in d:
            print('    columns:')
            for n in d['physical_column_names']:
                print('        %s' % n)


if __name__ == '__main__':
    sys.exit(main())
