# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import api, models
from odoo.tools import email_split

# Context key under which the raw routing headers travel from the mail gateway
# to `edi.exchange.record.message_new()`/`message_update()`.
INBOUND_HEADERS_KEY = "edi_inbound_headers"

# Headers `message_parse()` drops (it only keeps From/To/Cc/Delivered-To
# merged into `to`/`recipients`) but which tell who an email was *really*
# addressed to when a mailbox forwarded it to the Odoo alias.
_ROUTING_HEADERS = (
    "To",
    "Delivered-To",
    "X-Forwarded-For",
    "X-Forwarded-To",
)


class MailThread(models.AbstractModel):
    """Hand the raw routing headers of an inbound email to the exchange record.

    `mail.thread.message_parse()` flattens the envelope-ish headers into
    `msg_dict["to"]`/`["recipients"]`, which loses exactly what is needed to
    tell the shop-side mailbox that forwarded an email from the Odoo alias it
    was forwarded to (`To` vs. `Delivered-To`, `X-Forwarded-For`, ...). Adding
    keys to `msg_dict` is not an option: the gateway passes it on to
    `message_post()` for every thread model, which rejects unknown keys. The
    parsed `email.message` is still at hand in `_message_route_process()`,
    which creates (`message_new()`) or updates (`message_update()`, for an
    email whose References collide with an earlier exchange) the record, so
    the headers ride along in the context, and only when a route targets an
    `edi.exchange.record`.
    """

    _inherit = "mail.thread"

    @api.model
    def _message_route_process(self, message, message_dict, routes):
        if any(route[0] == "edi.exchange.record" for route in routes or ()):
            headers = {
                header.lower().replace("-", "_"): [
                    address
                    for value in message.get_all(header, [])
                    for address in email_split(str(value))
                ]
                for header in _ROUTING_HEADERS
            }
            return super(
                MailThread, self.with_context(**{INBOUND_HEADERS_KEY: headers})
            )._message_route_process(message, message_dict, routes)
        return super()._message_route_process(message, message_dict, routes)
