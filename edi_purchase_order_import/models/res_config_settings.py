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

    edi_po_reply_allowed = fields.Char(
        string="Allowed Reply Addresses",
        config_parameter="edi_purchase_order_import.reply_allowed",
        help="Email addresses (orders@shop.example) and domains (@shop.example) "
        "that notices about imported purchase orders may be emailed to, "
        "separated by commas or spaces, besides the emails of internal users "
        "and companies. Notices are emailed to the shop mailbox that "
        "forwarded the vendor's email to Odoo, but only if it is listed here "
        "(or is a user's email): the addresses come from the headers of the "
        "inbound email.",
    )
