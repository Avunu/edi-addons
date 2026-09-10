# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class BaseImportPdfTemplate(models.Model):
    _inherit = "base.import.pdf.template"

    extraction_mode = fields.Selection(
        selection_add=[
            ("plaintext", "Plain Text"),
            ("html", "HTML"),
        ],
        ondelete={"plaintext": "set default", "html": "set default"},
    )
