# Import Create Missing

Adds a **Create New Document if Not Found** checkbox to a `base.import.pdf.template.line`, and a **New Document Values** table that appears once it's checked. When this line's search (Search field / Search subfield) misses, instead of leaving the line unresolved (the base module's own behaviour: fall back to `Fixed value`/`default_value`, or the raw extracted text), the missing document is created and linked - filled in from the New Document Values table.

## Why

`custom/product_napaonline_lookup` already does this for one specific case (creating `product.product` records from a NAPA part number via the parse.bot API). This module generalizes the same idea to any linked model, filled from the template's own extracted data instead of an external API: a Fixed value, or a Variable value pulled out with the same `Pattern` regex (and, if `import_create_missing_xberg` is also installed, the same JSONPath narrowing) the line itself uses.

## How it works

**New Document Values** is a list of `base.import.pdf.template.line.create.value` rows - click a row (or **Add a line**) to open it, the same list-opens-a-form pattern the template's own **Lines** tab uses for `base.import.pdf.template.line`. It's not an inline editable table: several of a row's fields are mutually exclusive depending on its **Field**/**Type** (a fixed value vs. a record picker vs. a pattern vs. a nested table), and a form can genuinely hide a field it doesn't need - an inline table's columns are always there whether or not that row uses them, which is confusing once there's more than one kind of value. The compact list shows a one-line **Value summary** instead.

Each row sets one field on the document to create:

-   **Field**: any field on the line's linked model (`Field`'s relation) - including a field inherited from a delegated parent model (e.g. `product.product`'s own fields as well as everything it delegates from `product.template`).
-   **Type**: `Fixed` or `Variable` - not shown for a one2many field (see below).
-   **Value** (Fixed only): a typed value - a plain input for most field types, a record picker for many2one/reference.
-   **Pattern** (Variable only): a regex, evaluated the same way the line's own `Pattern` is - once per row of a `lines` table (or once for a `header` line), in the same position/alignment as the line's own extracted values. For example, if the line's own `Pattern` finds a part number in every row of a table, a New Document Values row with `Pattern` set to match that table's Description column fills in `name` for the row at the same position.

The row a New Document Value's `Pattern` matched is paired to the line's own row **by position**: the 3rd match of a New Document Values row's pattern goes with the 3rd match of the line's own pattern. If a New Document Values row's pattern produces a different number of matches than the line itself does (a ragged extraction - usually a sign the pattern is wrong), **no document is created for any row of that line** and a warning is logged; positions are never silently paired incorrectly to avoid, say, naming one product after a different row's description.

The search field (if it's a plain field directly on the linked model, not a `one2many`/relation) is pre-filled with the value that was searched for and missed, so importing the same source again finds the just-created record instead of creating a duplicate - a New Document Values row for the same field overrides this if present.

Document creation only ever happens during a **real import** - `wizard.base.import.pdf.upload.line._process_form()` (used by both a manual upload and `import_from_email`'s EDI intake). A template's live preview (`import_preview`) or the standalone preview wizard never creates anything, even with `Create New Document if Not Found` checked - there is nothing to link the created record to.

### Nested one2many fields

If **Field** is a one2many (e.g. a newly-created vendor's own `bank_ids`, or a product's `seller_ids`), the row's Type/Value/Pattern disappear and a **Row Values** table takes their place - the exact same list-opens-a-form widget, one row per field of the one2many's own model (e.g. a bank account's `acc_number`), each with its own Type/Value/Pattern. Fill it in one field at a time, the same way you would the outer table.

A nested `Variable` row is matched a little differently than everywhere else in this module: since there's no per-row-relative pattern language to hand it "just this outer row's vendors," it searches the **whole document** fresh, and every `Variable` Row Values field is paired across the sub-records **by match position** instead - the 1st `acc_number` match goes with the 1st bank account, and so on. A `Fixed`-only nested field applies the same value to every sub-record; a one2many made entirely of `Fixed` rows creates exactly one sub-record. A mismatched match count between two `Variable` Row Values fields (same conservative rule as the outer table) skips the whole one2many rather than pairing rows incorrectly.

Because the whole document is searched fresh rather than scoped to the outer row, a `lines` line's one2many field gets the **same** sub-records on every row of its own table - there's currently no way to scope Row Values extraction to just one outer row. This is rarely a problem in practice: a nested one2many is most useful on a `header` line, where there's only one row to begin with (the concrete case this was built for: a single imported document, e.g. an email, describing one record with a repeating sub-list like several vendor bank accounts).

## Configuration

1. On a template line with a many2one `Field` and a `Search field` set, check **Create New Document if Not Found**.
2. Add rows to **New Document Values** for whatever fields the new document needs (at minimum, usually its name/label).
3. Import a document containing a value the search won't find.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i import_create_missing \
  --test-enable --test-tags /import_create_missing --stop-after-init
```
