# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class MailMessage(models.Model):
    _inherit = "mail.message"

    edi_notice_outstanding = fields.Boolean(
        string="Outstanding EDI Notice",
        copy=False,
        # the flag decides whose inbox notifications get cleared: not for
        # whoever may write the message (its author, a recipient) to set
        groups="base.group_system",
        help="Notice posted by purchase.order._edi_post_notice(outstanding=True): "
        "its inbox notifications are cleared by purchase.order._edi_clear_notices().",
    )
