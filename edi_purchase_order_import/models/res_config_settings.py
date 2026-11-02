# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    edi_po_notify_group_id = fields.Many2one(
        "res.groups",
        string="Notify Group on Imported Purchase Orders",
        config_parameter="edi_purchase_order_import.notify_group_id",
        help="Group whose users are notified (Messages/Inbox) when an "
        "inbound EDI/email order confirmation creates and confirms a "
        "purchase order. Defaults to Purchase: Administrator.",
    )
