# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class EdiExchangeType(models.Model):
    _inherit = "edi.exchange.type"

    import_template_id = fields.Many2one(
        comodel_name="base.import.pdf.template",
        string="Import Template",
        help="Template used to turn this exchange type's incoming file into "
        "an Odoo record. Only meaningful for input types processed by the "
        "generic 'Import by template' processor - set that as this type's "
        "Processor to use it.",
    )
