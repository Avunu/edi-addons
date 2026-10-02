# Import via Xberg

Adds an `xberg` extraction mode to `base_import_pdf_by_template`, backed by the `xberg` Python library (the `xberg` PyPI package - prebuilt wheels, no Rust toolchain or Nix build required), and an optional JSONPath pre-filter on template lines for templates using that mode.

## Why

`base_import_pdf_by_template` flattens every source document into one text blob and pulls fields out of it with per-line regexes. That mostly still works once the source is structured JSON instead of flat text - a regex is still a fine tool for pulling a value out of *some* text - but the "some text" is now often a big, noisy JSON document rather than a clean paragraph, and a template line has no way to narrow that down before its regex has to search all of it. `xberg` parses a PDF (or HTML, email, ...) into a structured document with a real `tables[].cells[][]` grid instead of flat text; this module lets a line's regex search just the slice of that document a JSONPath expression selects, instead of the whole thing.

An earlier version of this module shelled out to the `xberg` CLI (still packaged in `flake.nix` as `packages.xberg`, kept there as a standalone tool independent of this module). It now calls the `xberg` Python library directly instead - see "Why the library instead of the CLI" below. An even earlier version made `pattern` itself a JSONPath expression on an `xberg` template (replacing regex outright); that traded away the ability to *refine* a selected value - e.g. pull the trailing digits out of an item code JSONPath already located - so `pattern` is a plain regex again, on every template regardless of extraction mode, with JSONPath demoted to an optional pre-filter.

## What it adds

-   `extraction_mode = "xberg"` on `base.import.pdf.template` (and, because the template's and the preview wizard's `extraction_mode` are two independent Selections - see `WizardBaseImportPdfPreview` - on `wizard.base.import.pdf.preview` too). `_pdf_text_extraction_xberg()` runs the extraction through `xberg.extract()` and returns the resulting document, converted to JSON, as the "page text" - so a pattern reads `$.content` or `$.tables[...]` directly (no wrapper object), matching the shape documented below.
-   `cellsByHeader` / `cellsByIndex` added to every entry in `tables[]`, alongside (never replacing) its raw `cells` grid - see "Reading a table by column" below.
-   `xberg_config` on the template - an optional JSON object merged into xberg's `FileExtractionConfig` for that template's extractions (e.g. `{"ocr": {"enabled": true}}`). Passed straight through to the library; see xberg's own documentation for the full schema. Left blank, extraction uses xberg's defaults.
-   `xberg_jsonpath` on `base.import.pdf.template.line` - only meaningful on an `xberg` template, and optional even there. When set, `pattern`'s regex is matched against what this JSONPath selects (one match per line, so `re.MULTILINE`-style patterns work the same way they already do for the base module's own "lines" extraction) instead of against the whole document. Left blank, `pattern` matches the whole document as it always has - nothing changes for a line that doesn't set it.
-   `xberg_jsonpath_preview` - a live, read-only preview of exactly what `xberg_jsonpath` currently selects (each match numbered, one per line), shown right under the field in the line dialog. It's the narrowing step made visible on its own, *before* `pattern` even enters the picture - write and check the JSONPath first, see the values it actually pulls out, then write `pattern`'s regex against those. Needs a sample document on the template (`import_preview`'s Sample Data tab) to have anything to preview against; without one it says so instead of showing nothing. This is a soft integration, not a hard dependency on `import_preview` - see the comment on `_xberg_jsonpath_preview_depends()`.
-   `_get_field_value()`/`_get_column_values()` overrides that apply that narrowing before delegating to the base module's (`_get_field_value`) and `base_import_pdf_by_template_engine`'s (`_get_column_values`) own regex logic, completely unmodified - `pattern` is never anything but a real regex, so there is no `_process_value()` override here at all, and no special-casing anywhere else in the pipeline.

## Why the library instead of the CLI

The `xberg` PyPI package ships prebuilt wheels for Linux and macOS (both x86\_64 and arm64), so `pip install xberg` works anywhere a matching wheel exists - no Rust toolchain, no Tesseract/Leptonica/onnxruntime dev headers, none of the machinery `flake.nix`'s `packages.xberg` needs to build the CLI from source. It's also meaningfully faster per call (no process spawn, no re-parsing CLI args), and error handling is a normal Python exception instead of a subprocess return code and stderr text to parse.

The tradeoff: `xberg.extract()` is `async def`\-only, so `_pdf_text_extraction_xberg()` bridges with `asyncio.run()` (safe to call from any thread - each call gets its own event loop, and Odoo's threaded workers never run one of their own). More significantly, the library's result objects (`ExtractedDocument`, `Table`, `Metadata`, ...) are native compiled classes with no `to_json()`/`to_dict()` - only an asymmetric `from_json()` classmethod to build one _from_ JSON. `_to_jsonable()` (in `wizards/wizard_base_import_pdf_mixin.py`) walks the object graph generically instead (public, non-callable attributes via `dir()`), which is how a template's patterns get something to match against at all. It deliberately drops binary payloads (e.g. an extracted image's raw bytes) rather than embedding them - a pattern operates on text and table structure, never on pixel data, and inlining base64 into the JSON would make it expensive to `json.loads()` on every pattern evaluation.

## Configuration

-   `xberg_config` (per template, see above) - the primary way to tune an extraction (OCR, content format, table extraction, ...).
-   `import_via_xberg.timeout` (`ir.config_parameter`) - extraction timeout in seconds, injected into the config as `timeout_secs` when the template's own `xberg_config` doesn't set one. Default `300`.

## Reading a table by column

A table's raw `cells` is a plain `[[row], [row], ...]` grid - fine for one specific cell (`$.tables[0].cells[0][1]`), but there is no way to express "this column, across every row" without hardcoding its position, and that position breaks the moment column order shifts between two documents from the same sender.

So every table also gets two derived views, computed by `_transpose_table_cells()` treating row 0 as column headers:

-   `cellsByHeader`: one object per data row (row 0 itself excluded), keyed by that column's header text - `xberg_jsonpath = "$.tables[0].cellsByHeader[*].Item"` narrows to every row's `Item` value regardless of which column it's actually in, one per line, ready for `pattern` to refine further (or just `pattern = "(.+)"` to take each value as-is).
-   `cellsByIndex`: the same rows, keyed by stringified column index (`"0"`, `"1"`, ...) instead - always present even for a column whose header cell is blank (an image-only column, say), and immune to two columns sharing the same header text (`cellsByHeader` keeps only the later one in that case).

**Not every table has a header row**, though - most of the small tables in a real document are label/value pairs (`[["Order #:", "Y000000001:01"], ["Dealer:", "H000 - Example Truck Center"], ...]`) with no header semantics at all. Treating row 0 as a header there would turn the first pair's *values* into header keys for the second pair - nonsense. Rather than guess which shape a table is, `cellsByHeader`/`cellsByIndex` come back empty (`[]`) for a table with no real header, and `cells` is always left untouched alongside them - use whichever view actually fits the table you're looking at (check the live preview, or `import_preview`'s sample data, before writing the pattern).

## JSONPath + regex quick reference

Verified against `jsonpath-ng` 1.8.0 and a real extraction of the synthetic fixture `tests/data/sample_parts_invoice.pdf`. Each row below is one line's `xberg_jsonpath` (the narrowing step) paired with a `pattern` regex (the refining step) that runs against whatever it selects:

| `xberg_jsonpath` | narrows to | `pattern` | result |
|---|---|---|---|
| _(blank)_ | the whole document | `"lat":\s*"([\d.]+)"` | matches directly against the raw JSON, same as any non-`xberg` template |
| `$.tables[0].cells[1][2]` | `201P/90-0013` | `(\d+)$` | `0013` - select the whole cell, then refine it |
| `$.tables[0].cellsByHeader[*].ITEM` | one line per row's `ITEM` | `(\d+)$` | `['0013', ...]` - one refined value per row |

⚠️ `cells[1:][*][2]` is a trap when writing a JSONPath against the raw `cells` grid directly: after a slice, `[*]` descends _into the strings themselves_ and yields individual characters, not row values. Use `[1:].[2]` (a dot before the trailing index) to stay on rows - or use `cellsByHeader`/`cellsByIndex` instead, which don't need a slice at all.

`jsonpath_ng.ext` filter syntax (`[?(@.x=="y")]`) targets dicts; `cells` is an array of arrays, so filtering a header cell by its label is not generally expressible there - `cellsByHeader`/`cellsByIndex` exist precisely to sidestep that.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i import_via_xberg \
  --test-enable --test-tags /import_via_xberg --stop-after-init
```

Runs a real extraction against the committed PDF fixture (no CLI/PATH dependency to skip around), exercises the JSONPath-narrowing-then-regex flow and the `xberg_jsonpath_preview` compute (`test_xberg_jsonpath_narrowing.py`) - including the blank-`xberg_jsonpath` fallback, non-`xberg` templates ignoring it entirely, a missing sample document, no matches, and an invalid expression rendering instead of raising - and unit-tests `_to_jsonable()` and `_transpose_table_cells()` directly (bytes dropped, cycles and depth bounded; blank/duplicate headers, ragged rows, and header-less tables handled without corrupting or losing data).
