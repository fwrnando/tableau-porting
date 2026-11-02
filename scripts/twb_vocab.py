#!/usr/bin/env python3
"""Validation layer 7: find every hard-coded DATA VALUE in a workbook, and
optionally rewrite them when the new model spells things differently.

    # what literals does this workbook compare against?
    uv run --no-project python twb_vocab.py WB.twb --report

    # do these values still exist in the new model?
    uv run --no-project python twb_vocab.py WB.twb --check-domain North South West

    # translate old vocabulary -> new, everywhere it hides
    uv run --no-project python twb_vocab.py WB.twb --rewrite 'OLD=New' ... --out NEW.twb

A value that EXISTS is not the same as a value that MATCHES. Filters compare
literals; if the new model spells the value differently the filter silently
returns nothing, the dashboard is blank, and nothing errors.

Values hide in at least six contexts. Rewriting only formulas covers about half.
"""
import argparse, re, sys
from collections import Counter, defaultdict
import twblib as T

QUOTED = re.compile(r'''(['"])(.+?)\1''')


def _is_field_ref(value):
    """Filter/sort members often hold FIELD references (measure-name shelves),
    not data values. Those are noise here."""
    return value.lstrip('"\'').startswith('[')


def harvest(root, live_only=True):
    """{context: Counter(value)} of quoted literals and raw member values."""
    found = defaultdict(Counter)
    for ctx, sites in T.literal_sites(root).items():
        for value, _setter in sites:
            if ctx == 'formula':
                text = T.strip_comments(value) if live_only else value
                for m in QUOTED.finditer(text):
                    found[ctx][m.group(2)] += 1
            elif ctx in ('alias value',):
                found[ctx][value] += 1
            elif _is_field_ref(value):
                continue
            else:
                for m in QUOTED.finditer(value):
                    found[ctx][m.group(2)] += 1
                if not QUOTED.search(value) and value.strip() not in ('%all%', '%null%'):
                    found[ctx][value.strip()] += 1
    return found


def rewrite(root, mapping):
    """Apply {old: new} across every literal site. Quoted values keep their quotes."""
    counts = Counter()
    pat = re.compile(r'''(['"])(%s)\1''' %
                     '|'.join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
    plain = re.compile(r'^(%s)$' % '|'.join(re.escape(k) for k in mapping))

    for ctx, sites in T.literal_sites(root).items():
        for value, setter in sites:
            new = pat.sub(lambda m: m.group(1) + mapping[m.group(2)] + m.group(1), value)
            if ctx == 'alias value' and plain.match(value.strip()):
                new = mapping[value.strip()]
            if new != value:
                setter(new)
                counts[ctx] += 1
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('workbook')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--check-domain', nargs='*', metavar='VALUE',
                    help='values that DO exist in the new model; anything compared '
                         'against but not listed is a candidate mismatch')
    ap.add_argument('--rewrite', nargs='*', default=[], metavar='OLD=NEW')
    ap.add_argument('--include-comments', action='store_true')
    ap.add_argument('--out')
    ap.add_argument('--min', type=int, default=1, help='hide values seen fewer than N times')
    a = ap.parse_args()

    tree, root = T.load(a.workbook)

    if a.rewrite:
        mapping = dict(pair.split('=', 1) for pair in a.rewrite)
        counts = rewrite(root, mapping)
        print('rewritten by context:')
        for ctx, n in counts.most_common():
            print('   %-22s %d' % (ctx, n))
        if not a.out:
            print('\n(no --out given; nothing written)'); return 0
        T.enforce_child_order(root)
        T.save(tree, a.out)
        print('\nwrote %s' % a.out)
        return 0

    found = harvest(root, live_only=not a.include_comments)

    if a.check_domain is not None:
        domain = set(a.check_domain)
        print('values compared against, but NOT in the supplied domain:\n')
        suspicious = Counter()
        for ctx, counter in found.items():
            for val, n in counter.items():
                if val not in domain and not val.isdigit() and len(val) > 1:
                    suspicious[val] += n
        for val, n in suspicious.most_common(40):
            print('   x%-5d %s' % (n, val))
        print('\nNOTE: most of these are legitimate (labels, format strings, other '
              'dimensions).\n      Look for ones that LOOK like values of the field '
              'you are checking.')
        return 0

    print('data literals by context (live code only%s)\n'
          % ('' if not a.include_comments else ' + comments'))
    for ctx in ('formula', 'filter/set member', 'bin label', 'bin member',
                'parameter domain', 'alias key', 'alias value', 'manual sort'):
        counter = found.get(ctx)
        if not counter:
            continue
        print('--- %s (%d distinct)' % (ctx, len(counter)))
        for val, n in counter.most_common():
            if n >= a.min:
                print('      x%-5d %s' % (n, val))
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
