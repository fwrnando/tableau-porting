# tableau-porting

Local skill material for **porting and modernizing Tableau workbooks** by
transforming `.twb` XML and preserving `.twbx` package contents.

**Status: local working copy, not installed.** This folder is the maintained copy;
updating it does not register or install it into another application's skill path.
To install it for Claude Code: `ln -s "$PWD" ~/.claude/skills/tableau-porting` from this folder.

## What problem this covers

You have a workbook whose vizes are all built on a legacy datasource, and a newer
datasource that holds the same concepts under different names, types and
vocabulary. The worksheets, dashboards, layouts, formatting and several hundred
calculated fields are worth keeping; the data model underneath is not.

Rebuilding by hand is impractical past a few dozen worksheets. Rewriting the XML
is practical with layered validation: schema errors can prevent loading, while
other workbooks open with silently missing rows or wrong numbers. This material
covers both, including set-control integration and full-market share denominators.

## Files

| file | what it holds |
|---|---|
| `SKILL.md` | the workflow, start to finish |
| `references/twb-xml.md` | `.twb` structure: where things live, what the schema enforces |
| `references/failure-modes.md` | catalogue: symptom, diagnosis, fix (including downstream decks) |
| `references/validation.md` | the validation ladder + reusable checks |
| `references/transform-recipes.md` | code patterns for the transform itself |
| `references/market-share-selection.md` | sparse-market COMP retention, sets, nested LOD scope and alternatives |
| `references/transplant-recipes.md` | moving dashboards into a different, modern workbook: catalog mapping, shared filters, collisions, retiring views |
| `references/authoring-cleanup.md` | authoring names vs visible labels, scoped dependency tracing and safe unused-field removal |
| `scripts/` | runnable tooling: survey, validate, vocabulary, and a port skeleton |

## The one-line version

A field reference that *resolves* is not the same as a field reference that is
*legal*, and a value that *exists* is not the same as a value that *matches*.
Nearly every bug lives in those two gaps.

## Three habits that would have saved the most time

1. **Check the premise.** "Same fields, drop-in swap" is often neither. One query
   settles it.
2. **Copy the shape.** When unsure how an element should look, read one the
   application wrote — don't reason it out from the schema.
3. **Prove which bytes are being read.** When a fix appears not to take, check
   modification time and checksum before changing anything else.
