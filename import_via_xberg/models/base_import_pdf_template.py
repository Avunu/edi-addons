# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class BaseImportPdfTemplate(models.Model):
    _inherit = "base.import.pdf.template"

    extraction_mode = fields.Selection(
        selection_add=[("xberg", "Xberg")],
        ondelete={"xberg": "set default"},
    )
    xberg_config = fields.Text(
        string="Xberg configuration",
        help="A JSON object merged into xberg's `FileExtractionConfig` for "
        "this template's extractions, e.g. `{\"ocr\": {\"enabled\": true}}`. "
        "Left blank, extraction uses xberg's defaults. See the xberg "
        "documentation for the full configuration schema.",
    )
