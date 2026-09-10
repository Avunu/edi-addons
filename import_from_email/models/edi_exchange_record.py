# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import base64
import logging

from odoo import models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class EdiExchangeRecord(models.Model):
    """Bridge inbound mail into the EDI framework.

    `edi.exchange.record` already inherits `mail.thread`, so a `mail.alias`
    can point directly at it. This override of `message_new()` is what makes
    that alias useful: instead of the default mail.thread behaviour (create
    the record straight from `alias_defaults`, which can't work here since
    `type_id` is required and has no sensible default), it stores the
    message body as the exchange's source file and lets
    `edi.backend.create_record()` take over from there - the alias only
    needs to supply `backend_id` and `type_code` defaults to say which EDI
    backend and exchange type an incoming message belongs to.

    The raw HTML body is kept as-is (no html2plaintext here): the exchange
    record should hold what was actually received, and interpreting it is
    the extraction template's job (`extraction_mode = "html"`, added by this
    module's `wizard.base.import.pdf.mixin` override).
    """

    _inherit = "edi.exchange.record"

    def message_new(self, msg_dict, custom_values=None):
        custom_values = custom_values or {}
        backend_id = custom_values.get("backend_id")
        type_code = custom_values.get("type_code")
        if not backend_id or not type_code:
            # `type_id` (and, transitively, `backend_id`) is required on
            # this model, so the default mail.thread behaviour (create from
            # `custom_values` alone) cannot produce a valid record anyway.
            # An alias pointed at `edi.exchange.record` without both
            # defaults is a configuration mistake, not a case to fall back
            # silently on.
            raise UserError(
                self.env._(
                    "This mail alias is missing a 'backend_id' and/or "
                    "'type_code' default: cannot tell which EDI backend "
                    "and exchange type to file the incoming message under."
                )
            )
        backend = self.env["edi.backend"].browse(backend_id).exists()
        if not backend:
            raise UserError(
                self.env._("EDI backend #%s does not exist.", backend_id)
            )
        # Let the backend resolve `type_code` itself (`create_record()` ->
        # `_get_exchange_type_domain()`): it already knows how to match a
        # type pinned to this exact backend as well as one shared across
        # the whole backend type, so there is no need to duplicate that
        # lookup here.
        body = msg_dict.get("body") or ""
        filename = "{}.html".format(
            msg_dict.get("message_id")
            or self.env["ir.sequence"].next_by_code("edi.exchange")
        )
        logger.info(
            "Creating EDI exchange record (type=%s) from inbound email %s",
            type_code,
            msg_dict.get("message_id"),
        )
        return backend.create_record(
            type_code,
            {
                "exchange_file": base64.b64encode(body.encode()),
                "exchange_filename": filename,
                # The whole document is already in hand - there is no
                # separate "receive" round-trip to an external system, so
                # skip straight to "received" or `quick_exec` would never
                # pick this record up (it only looks at "input_received").
                "edi_exchange_state": "input_received",
            },
        )
