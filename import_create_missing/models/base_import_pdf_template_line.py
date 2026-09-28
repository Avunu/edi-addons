# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

#: The context key holding this row's `create_value_ids` values, keyed by
#: this line's own id: `{line_id: {create_value_id: raw_value, ...} | None}`.
#: Set by `base.import.pdf.template._get_field_values()`/
#: `_get_field_values_from_table_item()` (via `with_context()`) for exactly
#: one row (or the header) at a time, and ONLY when
#: `wizard.base.import.pdf.upload.line._process_form()` is actually running
#: a real import - never during a preview/onchange render. Its absence is
#: what makes a search miss inert everywhere except a real import, without
#: `create_missing` itself needing to know the difference.
CREATE_MISSING_VALUES_KEY = "import_create_missing_values"

#: The whole extracted document, set alongside `CREATE_MISSING_VALUES_KEY`
#: (same lifetime/guard). Every other field on a line is resolved from a
#: single already-matched value, but a `one2many` New Document Values row
#: (see `base.import.pdf.template.line.create.value._extract_one2many_
#: commands()`) has to search the WHOLE document again for its own nested
#: matches - there is no per-row-relative pattern language to hand it
#: just "this row's slice" instead.
CREATE_MISSING_TEXT_KEY = "import_create_missing_text"


class BaseImportPdfTemplateLine(models.Model):
    _inherit = "base.import.pdf.template.line"

    create_missing = fields.Boolean(
        string="Create New Document if Not Found",
        help="When this line's search (Search field / Search subfield "
        "above) misses, create the missing document instead of leaving "
        "the line unresolved - filled in from New Document Values below. "
        "Only meaningful when Field is a many2one with a Search field set; "
        "harmless but inert otherwise.",
    )
    create_value_ids = fields.One2many(
        comodel_name="base.import.pdf.template.line.create.value",
        inverse_name="line_id",
        string="New Document Values",
        copy=True,
    )

    def _get_record_search_from_value(self, value):
        record = super()._get_record_search_from_value(value)
        if record or not value or not self.create_missing:
            return record
        row = self.env.context.get(CREATE_MISSING_VALUES_KEY)
        if row is None:
            # Not a real import (a preview/onchange render, or another
            # caller entirely) - never create anything outside
            # `wizard.base.import.pdf.upload.line._process_form()`.
            return record
        row = row.get(self.id)
        if row is None:
            # `_get_table_info()` found this line's own value column
            # didn't line up with the other "lines" columns (a ragged
            # table) and already logged a warning there - nothing more to
            # do here than fall through to default_value/raw text, same
            # as any other unresolved miss.
            return record
        vals = self._prepare_create_missing_vals(value, row)
        try:
            with self.env.cr.savepoint():
                record = self.env[self.field_relation].create(vals)
        except Exception as err:  # pylint: disable=W8138
            _logger.warning(
                "Line %s: failed to create a missing %s record for %r: %s",
                self.id,
                self.field_relation,
                value,
                err,
            )
            env["ir.logging"].sudo().create(
                {
                    "name": f"Line {self.id}: failed to create a missing "
                    f"{self.field_relation} record for {value!r}: {err}",
                    "type": "server",
                    "dbname": self.env.cr.dbname,
                    "level": "warning",
                    "message": err,
                    "path": "base_import_pdf_template_line.py",
                    "func": "_get_record_search_from_value",
                    "line": "88",
                }
            )
            return self.env[self.field_relation]
        return record

    def _prepare_create_missing_vals(self, value, row):
        self.ensure_one()
        vals = {}
        text = self.env.context.get(CREATE_MISSING_TEXT_KEY)
        search_field = self.search_field_id
        if (
            search_field
            and not self.search_subfield_id
            and search_field.model_id.model == self.field_relation
            and search_field.ttype not in ("many2one", "many2many", "one2many")
        ):
            # Pre-fill the field the next import's search would look this
            # value up by, so re-importing the same document (or another
            # from the same source) finds this record instead of creating
            # a duplicate. A New Document Values row for the same field
            # (rare, but not forbidden) overrides this below.
            vals[search_field.name] = value
        for create_value in self.create_value_ids.sorted("sequence"):
            if not create_value.field_name:
                continue
            create_value_value = create_value._to_create_value(
                row.get(create_value.id), text=text
            )
            if create_value_value is None:
                continue
            vals[create_value.field_name] = create_value_value
        return vals

    def _preview_depends(self):
        """Soft integration with `import_preview` - see the identical
        pattern (and its full explanation) on `import_via_xberg`'s
        `_preview_depends()`. `create_missing`/`create_value_ids` don't
        change what THIS line itself extracts, but they do change what a
        search miss on it results in, so the live preview should still
        refresh when either changes."""
        return super()._preview_depends() + ["create_missing", "create_value_ids"]
