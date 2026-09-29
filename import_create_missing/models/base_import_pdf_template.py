# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

from odoo import models

from .base_import_pdf_template_line import (
    CREATE_MISSING_TEXT_KEY,
    CREATE_MISSING_VALUES_KEY,
)

_logger = logging.getLogger(__name__)

#: Set (via `with_context()`) by `wizard.base.import.pdf.upload.line.
#: _process_form()` for the duration of a real import only - see the long
#: comment on `CREATE_MISSING_VALUES_KEY`. Every method below is a no-op
#: (falls straight through to `super()`) unless this is set, so a preview
#: (`import_preview`'s sample-data compute, the line dialog's live match
#: preview, `wizard.base.import.pdf.preview`) never creates anything.
CREATE_MISSING_ENABLED_KEY = "import_create_missing"


class BaseImportPdfTemplate(models.Model):
    _inherit = "base.import.pdf.template"

    def _create_missing_lines(self):
        return self.line_ids.filtered(
            lambda x: x.related_model == "lines"
            and x.value_type != "fixed"
            and x.pattern
            and x.create_missing
        )

    def _get_table_info(self, text):
        res = super()._get_table_info(text)
        if not self.env.context.get(CREATE_MISSING_ENABLED_KEY):
            return res
        create_missing_lines = self._create_missing_lines()
        if not res or not create_missing_lines:
            return res
        table_rows = len(res["data"])
        by_line = {}
        for line in create_missing_lines:
            # Aligned against the line's OWN column, not the whole table:
            # the table is `zip_longest` over every "lines" line, so one
            # longer column elsewhere (a Unit Price that also matched a
            # loyalty price) would otherwise make every New Document Values
            # column look misaligned and silently block all creation.
            own_rows = len(line._get_column_values(text))
            by_line[line.id] = self._extract_create_missing_columns(
                line, text, own_rows, table_rows
            )
        res["create_missing"] = by_line
        res[CREATE_MISSING_TEXT_KEY] = text
        return res

    def _create_missing_column_rows(self, line):
        """The rows whose values `_extract_create_missing_columns()` must
        extract as table-aligned columns: this line's own Variable rows,
        plus - on a `lines` line - the Variable Row Values of each
        top-level one2many row, so each product's vendor row is built from
        its OWN table row (see
        `create.value._one2many_create_value()`)."""
        rows = self.env["base.import.pdf.template.line.create.value"]
        for create_value in line._top_level_create_values():
            if create_value.field_ttype == "one2many":
                if create_value._pairs_one2many_by_row():
                    rows |= create_value.child_value_ids
                continue
            rows |= create_value
        return rows.filtered(
            lambda row: row.field_name
            and row.value_type == "variable"
            and row.field_ttype != "one2many"
            and row._has_variable_source()
        )

    def _extract_create_missing_columns(self, line, text, row_count, table_rows=None):
        """This line's New Document Values columns, keyed by create-value
        id, each checked against `row_count` - the number of rows the
        line's OWN column produced - then padded with "" to `table_rows`
        (the whole table's length), since the caller reads one value per
        table row. Padded rows are past the end of this line's own column:
        their own cell is empty, so the search never runs and nothing is
        created for them.

        A column whose length doesn't match `row_count` is set to `None`
        rather than zipped in ragged - see the module README for why: a
        positional mismatch would silently pair a New Document Value with
        the wrong row instead of just producing no document, which is worse
        than not creating one at all. Why is logged where it can be found.
        """
        table_rows = max(table_rows or 0, row_count)
        columns = {}
        for create_value in self._create_missing_column_rows(line):
            values = create_value._extract_column(text)
            if len(values) != row_count:
                label = (
                    f"{create_value.parent_id.field_id.field_description} › "
                    if create_value.parent_id
                    else ""
                ) + (create_value.field_id.field_description or create_value.field_name)
                line._log_create_missing(
                    f"Line {line.id}: New Document Values row {create_value.id} "
                    f"({label}) extracted {len(values)} value(s) but the line "
                    f"itself has {row_count} row(s) - skipping document "
                    f"creation for every row of this line.",
                    "_extract_create_missing_columns",
                )
                columns[create_value.id] = None
            else:
                columns[create_value.id] = values + [""] * (table_rows - len(values))
        return columns

    def _get_field_child_values(self, table_info):
        create_missing = (table_info or {}).get("create_missing")
        if not create_missing:
            return super()._get_field_child_values(table_info)
        res = []
        if table_info and table_info["data"]:
            for index, data_line in enumerate(table_info["data"]):
                row_values = {}
                skip_line_ids = set()
                for line_id, columns in create_missing.items():
                    row = {}
                    for create_value_id, values in columns.items():
                        if values is None:
                            skip_line_ids.add(line_id)
                            continue
                        row[create_value_id] = values[index]
                    row_values[line_id] = None if line_id in skip_line_ids else row
                res_line = self.with_context(
                    **{
                        CREATE_MISSING_VALUES_KEY: row_values,
                        CREATE_MISSING_TEXT_KEY: table_info.get(CREATE_MISSING_TEXT_KEY),
                    }
                )._get_field_values_from_table_item(data_line)
                if res_line:
                    res.append(res_line)
        return res

    def _get_field_values(self, related_model, text):
        if related_model != "header" or not self.env.context.get(
            CREATE_MISSING_ENABLED_KEY
        ):
            return super()._get_field_values(related_model, text)
        create_missing_lines = self.line_ids.filtered(
            lambda x: x.related_model == "header"
            and x.value_type != "fixed"
            and x.create_missing
        )
        if not create_missing_lines:
            return super()._get_field_values(related_model, text)
        row_values = {}
        for line in create_missing_lines:
            row = {}
            for create_value in line._top_level_create_values():
                if not create_value.field_name or create_value.value_type != "variable":
                    continue
                if create_value.field_ttype == "one2many":
                    continue
                if not create_value._has_variable_source():
                    continue
                row[create_value.id] = create_value._extract_header(text)
            row_values[line.id] = row
        return super(
            BaseImportPdfTemplate,
            self.with_context(
                **{
                    CREATE_MISSING_VALUES_KEY: row_values,
                    CREATE_MISSING_TEXT_KEY: text,
                }
            ),
        )._get_field_values(related_model, text)
