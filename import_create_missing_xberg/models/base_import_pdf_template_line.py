# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from __future__ import annotations

from odoo import models


class BaseImportPdfTemplateLine(models.Model):
    _inherit = "base.import.pdf.template.line"

    def _create_missing_warning_depends(self):
        return super()._create_missing_warning_depends() + (
            "template_id.extraction_mode",
            "xberg_jsonpath",
            "create_value_ids.value_type",
            "create_value_ids.pattern",
            "create_value_ids.xberg_jsonpath",
            "create_value_ids.child_value_ids.value_type",
            "create_value_ids.child_value_ids.pattern",
            "create_value_ids.child_value_ids.xberg_jsonpath",
        )

    def _create_missing_config_warnings(self):
        """Name every Variable row that has no JSONPath of its own, on a
        line that narrows with one.

        The line's own Pattern only ever sees what its JSONPath selected -
        one cell per table row. A New Document Values row without its own
        JSONPath hands its Pattern the whole Xberg JSON document instead,
        where a pattern written for a single cell (`^[A-Z]+\\d+…`) typically
        matches nothing - so the column comes up short and no document is
        created for any row of the line. Easy to miss, because the row
        still LOOKS configured: it has a pattern.
        """
        warnings = super()._create_missing_config_warnings()
        if self.template_id.extraction_mode != "xberg" or not self.xberg_jsonpath:
            return warnings
        labels = self._rows_without_jsonpath(self._top_level_create_values())
        if labels:
            warnings.append(
                self.env._(
                    "No JSONPath, so the Pattern searches the whole document "
                    "instead of the line's cells: %s",
                    ", ".join(labels),
                )
            )
        return warnings

    def _rows_without_jsonpath(self, rows, prefix: str = "") -> list[str]:
        """Labels of the Variable rows in `rows` (recursing into each
        one2many row's Row Values) that have no `xberg_jsonpath`. A
        one2many row itself extracts nothing, so it is never named - only
        what is inside it."""
        labels: list[str] = []
        for row in rows.sorted("sequence"):
            if not row.field_id:
                continue
            label = row.field_id.field_description or row.field_name
            if row.field_ttype == "one2many":
                labels += self._rows_without_jsonpath(
                    row.child_value_ids, prefix=f"{prefix}{label} › "
                )
                continue
            # A pattern with nothing narrowing it. A row with neither set is
            # a different problem, already reported as missing/"No pattern"
            # where it matters.
            if row.value_type == "variable" and row.pattern and not row.xberg_jsonpath:
                labels.append(f"{prefix}{label}")
        return labels
