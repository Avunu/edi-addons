# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import base64
import logging
import re

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize, email_split

from .mail_thread import INBOUND_HEADERS_KEY

logger = logging.getLogger(__name__)

# Whoever can write to the mail alias controls the headers the reply addresses
# are read from, so never answer more than a handful of them.
MAX_REPLY_ADDRESSES = 5

# Mailbox providers anybody has an address at: a recipient on the sender's
# domain is a colleague of the sender only when the domain is not one of these.
_PUBLIC_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "ymail.com",
        "aol.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "mail.com",
        "zoho.com",
    }
)

# Senders nobody reads: never worth replying to.
_NO_REPLY = re.compile(
    r"^(?:no[-_.]*reply|do[-_.]*not[-_.]*reply|mailer[-_.]daemon|postmaster|bounces?)"
    r"(?:[-_.+=].*)?$",
    re.IGNORECASE,
)


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

    inbound_message_id = fields.Char(
        string="Inbound Message-Id",
        copy=False,
        index="btree_not_null",
        readonly=True,
        help="Message-Id header of the email this exchange was created from.",
    )
    inbound_subject = fields.Char(
        string="Inbound Subject",
        copy=False,
        readonly=True,
        help="Subject of the email this exchange was created from.",
    )

    inbound_reply_to = fields.Char(
        string="Inbound Reply Addresses",
        copy=False,
        readonly=True,
        help="Comma-separated addresses a reply to the email this exchange was "
        "created from should go to: the shop-side mailbox it was addressed to "
        "or forwarded from (never the original sender), or the person who "
        "forwarded it by hand. Empty when nothing could be determined.",
    )

    def _inbound_instance_addresses(self):
        """Normalized email addresses that belong to this Odoo instance: the
        bounce/catchall/default-from address of every alias domain, every
        mail alias (an alias with local-part detection matches that local part
        on any domain, so it is kept as a bare ``localpart@``), and the legacy
        ``mail.*`` system parameters.

        Read as sudo: whoever feeds the gateway (alias owner, cron) may not be
        allowed to read aliases, and only addresses are returned.
        """
        addresses = set()
        for domain in self.env["mail.alias.domain"].sudo().search([]):
            addresses.update(
                email_normalize(address)
                for address in (
                    domain.bounce_email,
                    domain.catchall_email,
                    domain.default_from_email,
                )
                if address
            )
        for alias in self.env["mail.alias"].sudo().search([]):
            if alias.alias_full_name:
                addresses.add(email_normalize(alias.alias_full_name))
            if alias.alias_incoming_local and alias.alias_name:
                addresses.add(f"{alias.alias_name.lower()}@")
        params = self.env["ir.config_parameter"].sudo()
        catchall_domain = params.get_param("mail.catchall.domain")
        if catchall_domain:
            for key in (
                "mail.catchall.alias",
                "mail.bounce.alias",
                "mail.default.from",
            ):
                alias_name = params.get_param(key)
                if alias_name:
                    addresses.add(f"{alias_name}@{catchall_domain}".lower())
        addresses.discard(False)
        return addresses

    def _inbound_reply_addresses(self, msg_dict, headers=None):
        """The addresses a reply to the inbound email should go to.

        A shop mailbox (typically Gmail) receives the vendor's email and a
        forwarding rule passes it on to the Odoo mail alias. The reply must
        go back to that shop mailbox, never to the vendor. So, from the
        headers ``message_parse()`` drops (see ``mail_thread.py``):

        - the mailbox that forwarded the email is named by ``X-Forwarded-For``
          (Gmail's forwarding rules add it): when it names someone, that is the
          answer. Otherwise the addresses the email was originally addressed
          to (``To``) are used, leaving out colleagues of the sender (same
          domain, unless that is a public mailbox provider). ``Cc`` is ignored;
        - whatever belongs to this Odoo instance (see
          ``_inbound_instance_addresses()``), the original sender (the vendor),
          no-reply style addresses and the Odoo-side delivery targets are left
          out. Only the *top-most* ``Delivered-To`` is a delivery target (the last
          hop, added by the Odoo side's mail server), as is ``X-Forwarded-To``,
          which names where a forwarding rule sends the email. The
          ``Delivered-To`` headers below were added by the shop's own mail
          server, as the email passed through the shop mailbox, and name that
          very mailbox. ``X-Original-To`` is not trusted either way;
        - when nothing is left, the email was forwarded by hand to the alias
          (its ``To`` was only the alias): fall back to the forwarder, i.e. the
          ``From`` address, unless that is an instance or no-reply address too;
        - at most ``MAX_REPLY_ADDRESSES`` addresses are kept: whoever can write
          to the alias controls these headers.

        :param dict msg_dict: as given to ``message_new()``
        :param dict headers: lists of addresses per routing header, keyed by
          lower-cased name with ``_`` for ``-`` (``to``, ``x_forwarded_for``,
          ...), as put in the context by ``_message_route_process()``; without
          it ``msg_dict["to"]`` (``To`` + ``Delivered-To``) is all there is.
        :return: list of normalized email addresses, possibly empty
        """
        headers = headers or {"to": email_split(msg_dict.get("to") or "")}

        def normalized(*names):
            found = (email_normalize(a) for n in names for a in headers.get(n, ()))
            return [a for a in dict.fromkeys(found) if a]

        sender = email_normalize(msg_dict.get("email_from") or "")
        sender_domain = sender.partition("@")[2] if sender else ""
        instance = self._inbound_instance_addresses()
        delivery_targets = set(
            normalized("delivered_to")[:1] + normalized("x_forwarded_to")
        )

        def usable(address):
            if address in instance or address in delivery_targets:
                return False
            if f"{address.partition('@')[0]}@" in instance:
                return False
            return not _NO_REPLY.match(address.partition("@")[0])

        def colleague_of_sender(address):
            domain = address.partition("@")[2]
            return domain == sender_domain and domain not in _PUBLIC_MAIL_DOMAINS

        addresses = [
            a for a in normalized("x_forwarded_for") if a != sender and usable(a)
        ]
        if not addresses:
            addresses = [
                a
                for a in normalized("to")
                if a != sender and usable(a) and not colleague_of_sender(a)
            ]
        if not addresses and sender and usable(sender):
            addresses = [sender]
        return addresses[:MAX_REPLY_ADDRESSES]

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
            raise UserError(self.env._("EDI backend #%s does not exist.", backend_id))
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
                # Remembered on the record itself, not looked up later from
                # the mail.message the mail gateway posts: with `quick_exec`
                # the exchange is processed *inside* `create_record()`, i.e.
                # before the gateway has posted the inbound message on this
                # record, so processors (which may want to reply to the
                # email in the same thread) could not find it there.
                "inbound_message_id": msg_dict.get("message_id") or False,
                "inbound_subject": msg_dict.get("subject") or False,
                "inbound_reply_to": ", ".join(
                    self._inbound_reply_addresses(
                        msg_dict, self.env.context.get(INBOUND_HEADERS_KEY)
                    )
                )
                or False,
            },
        )

    def message_update(self, msg_dict, update_vals=None):
        """Never treat an inbound email as an update to a previous exchange.

        Odoo's mail gateway (`mail.thread.message_route()`) resolves an
        inbound message as "a reply" purely from its References/In-Reply-To
        headers matching a stored Message-Id - it does not require the
        message to actually be about the same document. Several mail
        clients keep every forwarded email under one subject/conversation
        (e.g. repeated manual forwards of separate purchase orders that
        happen to share an identical subject line), so their References
        chains collide with a previously received exchange even though each
        is a distinct document - and Odoo would otherwise silently fold the
        new one into the old record's chatter via this method instead of
        ever calling `message_new()` for it. Every inbound EDI email is its
        own independent exchange, so redirect through `message_new()`
        instead.

        This is also how the gateway reaches an existing exchange when the
        email's References collide with it, and then it gives no
        `update_vals`: the new exchange is filed under the backend and type
        of the one the email collided with.
        """
        defaults = {}
        if self:
            defaults = {
                "backend_id": self[:1].backend_id.id,
                "type_code": self[:1].type_id.code,
            }
        return self.message_new(msg_dict, {**defaults, **(update_vals or {})})
