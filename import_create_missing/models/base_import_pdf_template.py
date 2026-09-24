# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

from odoo import models

from .base_import_pdf_template_line import CREATE_MISSING_VALUES_KEY

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
        row_count = len(res["data"])
        by_line = {}
        for line in create_missing_lines:
            by_line[line.id] = self._extract_create_missing_columns(line, text, row_count)
        res["create_missing"] = by_line
        return res

    def _extract_create_missing_columns(self, line, text, row_count):
        """This line's `create_value_ids` columns, keyed by
        `create_value.id`, each padded/rejected against `row_count` (the
        number of rows the line's OWN column produced). A column whose
        length doesn't match `row_count` is set to `False` for every row
        rather than zipped in ragged - see the module README for why: a
        positional mismatch would silently pair a New Document Value with
        the wrong row instead of just producing no document, which is
        worse than not creating one at all.
        """
        columns = {}
        for create_value in line.create_value_ids:
            if not create_value.field_name or create_value.value_type != "variable":
                continue
            if not create_value._has_variable_source():
                continue
            values = create_value._extract_column(text)
            if len(values) != row_count:
                _logger.warning(
                    "Line %s: New Document Values row %s (%s) extracted "
                    "%s value(s) but the line itself has %s row(s) - "
                    "skipping document creation for every row of this "
                    "line.",
                    line.id,
                    create_value.id,
                    create_value.field_name,
                    len(values),
                    row_count,
                )
                columns[create_value.id] = None
            else:
                columns[create_value.id] = values
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
                    **{CREATE_MISSING_VALUES_KEY: row_values}
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
            for create_value in line.create_value_ids:
                if not create_value.field_name or create_value.value_type != "variable":
                    continue
                if not create_value._has_variable_source():
                    continue
                row[create_value.id] = create_value._extract_header(text)
            row_values[line.id] = row
        return super(
            BaseImportPdfTemplate,
            self.with_context(**{CREATE_MISSING_VALUES_KEY: row_values}),
        )._get_field_values(related_model, text)
