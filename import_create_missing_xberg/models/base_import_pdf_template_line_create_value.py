# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import re

from odoo import fields, models


class BaseImportPdfTemplateLineCreateValue(models.Model):
    _inherit = "base.import.pdf.template.line.create.value"

    xberg_jsonpath = fields.Char(
        string="JSONPath",
        help="Optional, only meaningful on an Xberg template. Selects one "
        "value per JSONPath match, in the same order/alignment as the "
        "line's own matches - e.g. "
        "$.tables[1].cellsByHeader[*]['Description'] to fill this field "
        "from the same table row the line's own Pattern found a part "
        "number in. If Pattern is also set, it's matched against each "
        "JSONPath match individually (never against all matches joined "
        "together - a blank/multi-line match would otherwise desync this "
        "column from the line's own rows). Left blank, Pattern behaves "
        "as it does everywhere else on this row: a plain regex over the "
        "whole extracted document.",
    )

    def _has_variable_source(self):
        return super()._has_variable_source() or bool(self.xberg_jsonpath)

    def _proxy_line_vals(self):
        vals = super()._proxy_line_vals()
        vals["xberg_jsonpath"] = self.xberg_jsonpath
        return vals

    def _extract_column(self, text):
        self.ensure_one()
        line = self.line_id
        if line.extraction_mode != "xberg" or not self.xberg_jsonpath:
            return super()._extract_column(text)
        proxy = self._proxy_line()
        matches = proxy._jsonpath_matches(self.xberg_jsonpath, text)
        values = []
        for match in matches:
            match_text = proxy._jsonpath_to_text(match.value)
            if not self.pattern:
                values.append(match_text)
                continue
            found = re.search(self.pattern, match_text)
            if not found:
                values.append("")
            elif found.groups():
                values.append(found.group(1) or "")
            else:
                values.append(found.group(0))
        return values
