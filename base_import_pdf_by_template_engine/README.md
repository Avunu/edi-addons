# Base Import Pdf by Template - Engine

Two small extension points on `base_import_pdf_by_template`'s models, factored out so a third-party module can plug in a different pattern language (JSONPath, ...) or build tooling around pattern matching (a live preview, ...) without overriding - and duplicating - whole methods from the base module.

## Why

The base module hardcodes regex in three places: table-column extraction (`_get_table_info_data`), header extraction (`_get_field_value`), and value post-processing (`_process_value`). The first two are easy to override per line. The third is not, because a pattern engine whose *selection* step already consumes the pattern (a JSONPath expression finds its match while extracting the value, unlike a regex which is re-applied inside `_process_value` on top of an already-extracted string) still needs `_process_value`'s ~25-line tail - date/float conversion, `mapped_ids`, `search_field_id`, `default_value` - without re-running the pattern a second time.

This module adds two seams instead of solving that per consumer module:

-   `base.import.pdf.template.line._get_column_values(text)` - the values this line contributes to a "lines" table, as a column. `base.import.pdf.template._get_table_info_data()` is refactored to build each column by calling this per child line instead of inlining a regex loop, so overriding one line's extraction no longer means overriding table assembly too. As a side effect this also fixes two latent bugs in the base algorithm: an `IndexError` when no child line has a pattern yet, and a silent column-shift when one column has fewer matches than another (a short column is now padded with `""` rather than dropped, which keeps every later column of that row aligned with the right field).
-   `base.import.pdf.template.line._without_pattern()` - an in-memory twin of a line with `pattern` cleared, safe to call `super()._process_value(value)` on. Correctly falls through to the real record's values whether `self` is a saved record, or is itself already an in-memory/`NewId` record (an onchange, a live preview compute, or `odoo.tests.Form`) - the latter needs an explicit value copy rather than `new(origin=self)`, because a `NewId` origin of a `NewId` is silently dropped by `odoo.models.origin_ids()`, which would otherwise make every stored field on the twin fall back to its bare field default instead of the real value.

Neither seam introduces a new field, a new model, or a UI change on its own - see `import_via_xberg` (a JSONPath pattern engine) and `import_preview` (a live match preview) for modules that build on top of them.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i base_import_pdf_by_template_engine \
  --test-enable --test-tags /base_import_pdf_by_template_engine --stop-after-init
```
