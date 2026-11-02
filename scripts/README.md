# scripts

Pure stdlib, no dependencies. Run with `uv run --no-project python <script> ...`.

| file | role |
|---|---|
| `twblib.py` | shared library — parsing, reference rewriting, schema order, literal sites |
| `twb_survey.py` | recon: what's in a workbook and how it's assembled |
| `twb_validate.py` | validation layers 1-6, exits non-zero on failure |
| `twb_vocab.py` | layer 7: every hard-coded data value, by context; can rewrite them |
| `port_template.py` | skeleton for the transform itself — copy and fill in |
| `test_twb_validate.py` | stdlib regression fixtures for load, group-reference and set-control failures |
| `test_twblib.py` | sheet/action rename bindings, collision rejection and presentation preservation |

## Typical run

```sh
# 1. recon, both sides
uv run --no-project python twb_survey.py legacy.twb
uv run --no-project python twb_survey.py newmodel.twb --fields

# 2. what values does the old workbook compare against?
uv run --no-project python twb_vocab.py legacy.twb --report

# 3. port (copy port_template.py, fill in CONFIG, re-run as you iterate)
uv run --no-project python my_port.py

# 4. validate
uv run --no-project python twb_validate.py ported.twb --compare legacy.twb newmodel.twb \
    --stale federated.<old-a> federated.<old-b> LEGACY.SCHEMA

# 5. vocabulary
uv run --no-project python twb_vocab.py ported.twb --report
uv run --no-project python twb_vocab.py ported.twb --check-domain <values that exist in the new model>

# 6. semantics — query the warehouse. Not automatable here, and the only
#    layer that catches wrong NUMBERS.
```

## Notes

These tools take unpacked `.twb` XML, not a `.twbx` ZIP. Locate the workbook member
without changing the source archive. Packaging guidance is in
`../references/transform-recipes.md`.

`twb_validate.py` layer 1 checks every datasource's child order (including
Parameters), at most one direct groupfilter per filter, encoding-map cardinality,
and nonempty, column-only slices. Add a known-bad regression fixture when a new
schema error reveals another content constraint.

Layer 3 also checks that filter column references match their context: a
datasource-level filter names the plain column, a worksheet filter the qualified
instance.
It also rejects `none:...:nk` wrappers on categorical-bin groups, checking the
defining datasource so an ordinary same-named field elsewhere is not misclassified.
Layer 5 checks set-card/zone params in their own datasource and set-zone worksheets.
Valid single-source shared views are preserved, not mistaken for blend leftovers.

The order-pattern diff (layer 6) is deliberately **advisory** rather than failing:
most novel patterns are benign, and a check that cries wolf gets ignored. Read
them.

These checks do not implement Tableau's full schema or type inference and do not
prove numerical correctness, rendering or refresh. Keep exact baseline warnings
visible and fail new ones; do not globally suppress forecast or label warnings.

Run the regression suite from the skill folder:

```sh
uv run --no-project python -m unittest discover -s scripts -p 'test_*.py' -v
```

`twb_vocab.py --report` on the *source* workbook is the cheapest way to find the
vocabulary work up front, before it shows up as a blank dashboard.

Give transform scripts distinctive names. A file named after a stdlib module
(`inspect.py`, `types.py`, `json.py`) shadows it and breaks unrelated imports.
