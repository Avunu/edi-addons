# Import Create Missing - Xberg Bridge

Adds a **JSONPath** column to `import_create_missing`'s New Document Values table, on a line whose template uses the `xberg` extraction mode - the same idea as `import_via_xberg`'s own `xberg_jsonpath` on the line itself, applied to each New Document Values row instead.

`auto_install`s once both `import_create_missing` and `import_via_xberg` are installed; neither of those two depends on the other.

## Why a separate value per JSONPath match, not narrow-then-regex

`import_via_xberg`'s own `xberg_jsonpath` narrows the document down to matched text, joins every match with `\n`, and runs `Pattern`'s regex over the joined result with `re.MULTILINE` - exactly mirroring how the base module's own "lines" extraction works over flat text.

A New Document Values row can't safely do the same thing: it has to stay aligned, **value for value**, with the line's own extracted rows (see `import_create_missing`'s README on how they're paired by position). One blank match, or one match that itself contains a newline (a wrapped Description cell, say), would shift every later row in the joined-and-split text - silently pairing a product's name with the wrong part number. So this module evaluates `Pattern` (if set) against **each JSONPath match individually** instead: `xberg_jsonpath` selects the values, one per row, and `Pattern` (optional) just refines each one in place. A blank match stays a blank value at that position rather than disappearing and shifting everything after it.

## Configuration

On a New Document Values row (see `import_create_missing`), set **JSONPath** the same way you would on the line itself - e.g. if the line's own `Pattern`/JSONPath finds a part number at `$.tables[1].cellsByHeader[*]['Part\n Number']`, a row filling in `name` from that same table's Description column uses `$.tables[1].cellsByHeader[*]['Description']`. `Pattern` is optional here - leave it blank to use each matched value as-is.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i import_create_missing_xberg \
  --test-enable --test-tags /import_create_missing_xberg --stop-after-init
```
