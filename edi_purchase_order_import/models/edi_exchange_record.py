# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import json

from markupsafe import Markup

from odoo import fields, models


class EdiExchangeRecord(models.Model):
    """Hold notices of an imported purchase order until the mail gateway has
    posted the inbound email on this record.

    With ``quick_exec`` the order is created and confirmed *inside*
    ``message_new()``, so a notice would get a lower ``mail.message`` id than
    the inbound email it replies to. The mail gateway routes a reply to the
    message with the highest id among the ones listed in its ``References``:
    a reply to such a notice would be routed to this exchange record, which
    rejects it, instead of to the purchase order. Posting the notice right
    after the inbound email (see ``_message_post_after_hook``) gives it the
    higher id, so replies land on the order.
    """

    _inherit = "edi.exchange.record"

    edi_pending_notices = fields.Text(
        string="Pending Notices",
        copy=False,
        readonly=True,
        help="JSON list of notices of the purchase order created from this "
        "exchange, posted once the inbound email is on the chatter.",
    )

    def _edi_inbound_message_pending(self):
        """True when this exchange comes from an email that the mail gateway
        has not posted on its chatter yet (``quick_exec`` processing)."""
        self.ensure_one()
        if not self.inbound_message_id:
            return False
        return (
            not self.env["mail.message"]
            .sudo()
            .search_count(
                # on any record: see `_message_post_after_hook()`
                [("message_id", "=", self.inbound_message_id)],
                limit=1,
            )
        )

    def _edi_defer_notice(self, body, email, outstanding, message_post_kwargs):
        """Queue a notice for `_message_post_after_hook`.

        :return: False (nothing queued) when the notice cannot be stored, i.e.
          its ``message_post`` arguments are not JSON-serializable.
        """
        self.ensure_one()
        try:
            queued = json.dumps(
                {
                    "body": str(body),
                    "html": isinstance(body, Markup),
                    "email": email,
                    "outstanding": outstanding,
                    "kwargs": message_post_kwargs,
                }
            )
        except (TypeError, ValueError):
            return False
        queue = json.loads(self.sudo().edi_pending_notices or "[]")
        queue.append(json.loads(queued))
        self.sudo().edi_pending_notices = json.dumps(queue)
        return True

    def _message_post_after_hook(self, message, msg_values):
        super()._message_post_after_hook(message, msg_values)
        if message.message_type != "email" or not message.message_id:
            return
        # Not just `self`: an email whose References collide with an earlier
        # exchange is posted on *that* record (`message_update()`), while the
        # exchange created for it is the one holding the notices.
        pending = (
            self.env["edi.exchange.record"]
            .sudo()
            .search(
                [
                    ("inbound_message_id", "=", message.message_id),
                    ("edi_pending_notices", "!=", False),
                ]
            )
        )
        for exchange in pending:
            queue = json.loads(exchange.edi_pending_notices)
            exchange.edi_pending_notices = False
            order = exchange.sudo().record
            if not order or order._name != "purchase.order":
                continue
            for notice in queue:
                body = Markup(notice["body"]) if notice["html"] else notice["body"]
                order._edi_do_post_notice(
                    body,
                    notice["email"],
                    notice["outstanding"],
                    **notice["kwargs"],
                )
