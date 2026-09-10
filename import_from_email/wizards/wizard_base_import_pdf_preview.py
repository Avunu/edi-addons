# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class WizardBaseImportPdfPreview(models.TransientModel):
    _inherit = "wizard.base.import.pdf.preview"

    # `base.import.pdf.template.extraction_mode` and this field are two
    # independent Selections, not a related pair - `button_preview()` passes
    # the template's mode in as `default_extraction_mode`, so this one needs
    # the same values added or previewing an html/plaintext template raises
    # "Wrong value for .../extraction_mode" before the onchange even runs.
    extraction_mode = fields.Selection(
        selection_add=[
            ("plaintext", "Plain Text"),
            ("html", "HTML"),
        ],
        ondelete={"plaintext": "set default", "html": "set default"},
    )
