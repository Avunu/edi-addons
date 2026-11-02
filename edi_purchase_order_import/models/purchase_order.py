# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import _, models

NOTIFY_GROUP_PARAM = "edi_purchase_order_import.notify_group_id"


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _edi_confirm_and_notify(self):
        """Confirm this EDI-imported RFQ and post a needaction notification
        to whoever is configured to hear about it (Settings > Purchase),
        so it shows up in their Messages/Inbox systray and clicking it
        opens this order.
        """
        self.ensure_one()
        if self.state == "draft":
            self.button_confirm()
        partners = self._edi_notify_partners()
        if partners:
            self.message_post(
                body=_(
                    "Purchase order confirmed automatically from an "
                    "incoming EDI/email order confirmation."
                ),
                partner_ids=partners.ids,
                subtype_xmlid="mail.mt_comment",
            )

    def _edi_notify_partners(self):
        """The res.partner recordset to notify: every user in the group
        configured at Settings > Purchase (falling back to the built-in
        Purchase Administrator group if nothing's been configured yet).
        """
        param = self.env["ir.config_parameter"].sudo().get_param(NOTIFY_GROUP_PARAM)
        group = self.env["res.groups"].browse(int(param)).exists() if param else False
        if not group:
            group = self.env.ref(
                "purchase.group_purchase_manager", raise_if_not_found=False
            )
        return group.users.partner_id if group else self.env["res.partner"]
