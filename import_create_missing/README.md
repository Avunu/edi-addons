# Import Create Missing

Adds a **Create New Document if Not Found** checkbox to a `base.import.pdf.template.line`, and a **New Document Values** table that appears once it's checked. When this line's search (Search field / Search subfield) misses, instead of leaving the line unresolved (the base module's own behaviour: fall back to `Fixed value`/`default_value`, or the raw extracted text), the missing document is created and linked - filled in from the New Document Values table.

## Why

`custom/product_napaonline_lookup` already does this for one specific case (creating `product.product` records from a NAPA part number via the parse.bot API). This module generalizes the same idea to any linked model, filled from the template's own extracted data instead of an external API: a Fixed value, or a Variable value pulled out with the same `Pattern` regex (and, if `import_create_missing_xberg` is also installed, the same JSONPath narrowing) the line itself uses.

## How it works

**New Document Values** is a list of `base.import.pdf.template.line.create.value` rows - click a row (or **Add a line**) to open it, the same list-opens-a-form pattern the template's own **Lines** tab uses for `base.import.pdf.template.line`. It's not an inline editable table: several of a row's fields are mutually exclusive depending on its **Field**/**Type** (a fixed value vs. a record picker vs. a pattern vs. a nested table), and a form can genuinely hide a field it doesn't need - an inline table's columns are always there whether or not that row uses them, which is confusing once there's more than one kind of value. The compact list shows a one-line **Value summary** instead.

Each row sets one field on the document to create:

-   **Field**: any field on the line's linked model (`Field`'s relation) - including a field inherited from a delegated parent model (e.g. `product.product`'s own fields as well as everything it delegates from `product.template`).
-   **Type**: `Fixed`, `Variable` or `Odoo Default` - not shown for a one2many field (see below).
-   **Value** (Fixed only): a typed input chosen from the field's own type - a checkbox for a boolean, a number for integer/float/monetary, a dropdown for a selection, a date picker for a date, a record picker for a many2one/reference, and plain text for text/html/json.
-   **Pattern** (Variable only): a regex, evaluated the same way the line's own `Pattern` is - once per row of a `lines` table (or once for a `header` line), in the same position/alignment as the line's own extracted values. For example, if the line's own `Pattern` finds a part number in every row of a table, a New Document Values row with `Pattern` set to match that table's Description column fills in `name` for the row at the same position.
-   **Odoo Default** rows carry no value at all: the field is deliberately left out of the `create()` call so Odoo applies its own default. Used automatically for a required field whose default is computed at creation time (a date/datetime that means "now"), where freezing a value into the template would be wrong.

The row a New Document Value's `Pattern` matched is paired to the line's own row **by position**: the 3rd match of a New Document Values row's pattern goes with the 3rd match of the line's own pattern. If a New Document Values row's pattern produces a different number of matches than the line itself does (a ragged extraction - usually a sign the pattern is wrong), **no document is created for any row of that line** and a warning is logged; positions are never silently paired incorrectly to avoid, say, naming one product after a different row's description.

The search field (if it's a plain field directly on the linked model, not a `one2many`/relation) is pre-filled with the value that was searched for and missed, so importing the same source again finds the just-created record instead of creating a duplicate - a New Document Values row for the same field overrides this if present.

Document creation only ever happens during a **real import** - `wizard.base.import.pdf.upload.line._process_form()` (used by both a manual upload and `import_from_email`'s EDI intake). A template's live preview (`import_preview`) or the standalone preview wizard never creates anything, even with `Create New Document if Not Found` checked - there is nothing to link the created record to.

### Required fields are filled in for you

Checking **Create New Document if Not Found** pre-populates the table with every field the document genuinely requires - `create()` would reject the record without them - so there is nothing to look up by hand. The same happens when a one2many row's **Row Values** table is first opened: it fills with that sub-model's own required fields. **Add Required Fields** on an already-saved line does it on demand, for a line configured before this existed or whose target model has since gained a required field.

What lands in each row depends on whether Odoo itself has a default:

-   **No default** (e.g. a product's `name`): an empty `Variable` row. You still have to say where the value comes from - that is the point of surfacing it.
-   **A default** (e.g. a product's Product Type, Product Category, Unit of Measure): a `Fixed` row **pre-set to that Odoo default**, so the default is visible and editable instead of invisible.

The search field is never added, because it is already pre-filled with the value that missed (see below). Neither is a delegation link (`product.product.product_tmpl_id`), a computed field, or a one2many's own inverse - all three are set by the very same `create()`.

Required-field discovery follows delegated (`_inherits`) parents, so creating a `product.product` correctly asks for `product.template`'s fields too. Adding your own rows works exactly as before, and auto-population never touches, reorders or removes a row you added or edited - it only ever appends what is missing. Rows pointing at a model that is no longer the target (because **Field** was re-pointed) are dropped.

### The missing-values warning

A row whose required field still has no value is highlighted in the list and marked **Missing**, and the tab shows a banner naming every one of them - nested ones included, as `Bank Accounts › Account Number`. Saving the line while some are still unfilled shows a warning notification.

The warning is **advisory only**: the line saves, the dialog closes, and you can come back later. Nothing is blocked, because a template is usually built over several sittings and against a document you may not have in front of you. A required field with an Odoo default is never reported - Odoo fills it in.

### Nested one2many fields

If **Field** is a one2many (e.g. a newly-created vendor's own `bank_ids`, or a product's `seller_ids`), the row's Type/Value/Pattern disappear and a **Row Values** table takes their place - the exact same list-opens-a-form widget, one row per field of the one2many's own model (e.g. a bank account's `acc_number`), each with its own Type/Value/Pattern. Fill it in one field at a time, the same way you would the outer table. Row Values live only inside their one2many row: open **Vendors** to see its **Vendor** and **Vendor Product Code** - they are not listed in the outer table.

A product line always gets a **Vendors** (`seller_ids`) row, with its required **Vendor** inside, even though nothing makes `seller_ids` required: a product created without a vendor row can never be found again by vendor code, so every later import would create a duplicate.

How Row Values are matched depends on the line:

-   **`lines` line: one sub-record per row, from that row's own values.** Each Variable Row Value is extracted as a column aligned to the line's own table rows, exactly like any other New Document Values column - so on a two-item order, product A's vendor row gets A's vendor code and product B's gets B's. Fixed Row Values apply to every row's sub-record. A Row Values column that doesn't line up with the line's rows skips document creation for the whole line, same as an outer column does.
-   **`header` line: matched across the whole document.** With only one row to begin with, Row Values search the whole document and are paired **by match position** - the 1st `acc_number` match goes with the 1st bank account, and so on - so one header can create several sub-records (the case this was built for: an email describing one vendor with several bank accounts). A `Fixed`-only one2many creates exactly one sub-record, and a mismatched match count between two Variable Row Values skips the whole one2many rather than pairing rows incorrectly.

A one2many nested inside another one2many has no table row of its own, so it always uses the whole-document behaviour.

### When a document is not created

Every reason a document was not created is written to **Settings → Technical → Logging** (filter *Path* = `import_create_missing`), on its own database cursor. That matters: a failed creation usually fails the whole import, which rolls the import's own transaction back - a log entry written there would vanish with it. You will find either:

-   `failed to create a missing … record for '…': <reason>` - Odoo rejected the `create()`, and the reason is Odoo's own error; or
-   `… extracted N value(s) but the line itself has M row(s) - skipping document creation` - a New Document Values column (named, with its parent for a Row Value, e.g. `Vendors › Vendor Product Code`) didn't line up with the line's own rows.

On an Xberg template, the warning banner also names every Variable row whose Pattern has no JSONPath of its own on a line that uses one: that Pattern searches the whole JSON document instead of the line's cells, and usually comes up empty.

## Configuration

1. On a template line with a many2one `Field` and a `Search field` set, check **Create New Document if Not Found**. **New Document Values** fills itself with the document's required fields.
2. Fill in the rows that came up empty (the ones Odoo has no default for), and adjust any pre-set default you don't want. Add rows of your own for anything else the new document should carry.
3. Import a document containing a value the search won't find.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i import_create_missing \
  --test-enable --test-tags /import_create_missing --stop-after-init
```
