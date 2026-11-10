# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import ast
import re

from lxml import html as lxml_html
from markupsafe import Markup

from odoo import _, api, models
from odoo.tools import email_normalize

NOTIFY_GROUP_PARAM = "edi_purchase_order_import.notify_group_id"
REPLY_ALLOWED_PARAM = "edi_purchase_order_import.reply_allowed"
NOTICE_SUBTYPE = "edi_purchase_order_import.mt_edi_notice"
_REPLY_PREFIX = re.compile(r"^\s*re\s*:", re.IGNORECASE)


class PurchaseOrder(models.Model):
    """Confirm an EDI-imported purchase order and tell people about it.

    `_edi_post_notice()` is the one path every EDI-related notice about an
    order goes through (the confirmation notice here, the match suggestions
    of `repair_purchase_order_match`): an internal chatter note, an inbox
    notification (never an email) for the configured group, and optionally one
    email that threads as a reply to the inbound email, sent only to the
    shop-side mailbox it was addressed to or forwarded from.
    """

    _inherit = "purchase.order"

    # ------------------------------------------------------------
    # CONFIRMATION
    # ------------------------------------------------------------

    def _edi_confirm_and_notify(self):
        """Confirm this EDI-imported RFQ and post the confirmation notice
        (see `_edi_post_notice()`; outstanding, with email) to whoever is
        configured to hear about it (Settings > Purchase).
        """
        self.ensure_one()
        if self.state == "draft":
            self.button_confirm()
        self._edi_post_notice(
            _(
                "Purchase order confirmed automatically from an "
                "incoming EDI/email order confirmation."
            ),
            email=True,
            outstanding=True,
        )

    # ------------------------------------------------------------
    # NOTICES
    # ------------------------------------------------------------

    def _edi_post_notice(
        self, body, email=True, outstanding=True, **message_post_kwargs
    ):
        """Post a notice about this order.

        1. An *internal* note on the order, with the
           ``edi_purchase_order_import.mt_edi_notice`` subtype nobody is
           subscribed to: neither the vendor nor any other follower is
           notified by it, whatever the follower subscriptions.
        2. The users of the group configured at Settings > Purchase get it in
           their Odoo inbox (``needaction``) **only**: no email, even when
           their notification preference is "Email".
        3. With ``email=True`` and reply addresses known
           (`_edi_reply_addresses()`), exactly one email is sent, only to those
           addresses. It is a reply to the inbound email (subject
           ``Re: <inbound subject>``, ``In-Reply-To`` and first ``References``
           entry the inbound ``Message-Id``) and its ``Message-Id`` is the
           note's, so that the shop's answer is routed to this order by the
           mail gateway. Without reply addresses (e.g. an order created from
           an uploaded PDF) no email is sent at all.

        With ``outstanding=True`` the notice is one `_edi_clear_notices()`
        clears (marks its inbox notifications read for everybody) once the
        order does not need attention any more. The default
        `_edi_notice_still_needed()` is consulted first: when it is false,
        the note is still posted (and emailed, if asked) but nobody gets an
        inbox notification for it, as it would be cleared at once.

        When the email must thread after the inbound email but the mail
        gateway has not posted that one yet (``quick_exec``: the order is
        processed inside ``message_new()``), the whole notice is held back and
        posted right after it; replies then route to this order (the gateway
        picks the highest message id among the ``References``). The call then
        returns an empty recordset.

        :param body: text (escaped) or `Markup` (html) of the note
        :param bool email: also send the threaded email to the reply addresses
        :param bool outstanding: mark the notice as clearable by
          `_edi_clear_notices()`
        :param message_post_kwargs: extra `message_post()` arguments (e.g.
          ``subject``, ``author_id`` - OdooBot by default - ``attachment_ids``).
          ``partner_ids`` are notified in the inbox as well (internal users
          only). Must be JSON-serializable to be deferrable; otherwise the
          notice is posted right away.
        :return: the posted ``mail.message`` (empty when deferred)
        """
        self.ensure_one()
        exchange = self._edi_exchange_record()
        if (
            email
            and exchange
            and self._edi_reply_addresses()
            and exchange._edi_inbound_message_pending()
            and exchange._edi_defer_notice(
                body, email, outstanding, message_post_kwargs
            )
        ):
            return self.env["mail.message"]
        return self._edi_do_post_notice(body, email, outstanding, **message_post_kwargs)

    def _edi_do_post_notice(self, body, email, outstanding, **message_post_kwargs):
        """`_edi_post_notice()` without the deferral."""
        self.ensure_one()
        needed = not outstanding or self._edi_notice_still_needed()
        addresses = self._edi_reply_addresses() if email else []
        origin = self._edi_originating_email()
        partner_ids = set(self._edi_notify_partners().ids)
        partner_ids.update(message_post_kwargs.pop("partner_ids", None) or ())
        post_kwargs = {
            # OdooBot: nobody wrote this, and the author must not be skipped
            # as a recipient if the user running the import is in the group
            "author_id": self.env["ir.model.data"]._xmlid_to_res_id(
                "base.partner_root"
            ),
            "notify_author": True,
            **message_post_kwargs,
            "subtype_xmlid": NOTICE_SUBTYPE,
            "partner_ids": sorted(partner_ids),
            "edi_notice_mode": "inbox" if needed else "silent",
        }
        if origin.get("subject") and not post_kwargs.get("subject"):
            subject = " ".join(origin["subject"].split())
            post_kwargs["subject"] = (
                subject if _REPLY_PREFIX.match(subject) else f"Re: {subject}"
            )
        # sudo: this runs from the mail gateway, a cron or a queue job, as
        # whoever owns the alias or the job - possibly not allowed to post on
        # purchase orders or to create notifications. The posted content and
        # the recipients are fixed here; nothing is exposed to the caller.
        order = self.sudo().with_context(mail_create_nosubscribe=True)
        message = order.message_post(body=body, **post_kwargs)
        if outstanding and needed:
            message.sudo().edi_notice_outstanding = True
        if addresses:
            order._edi_send_notice_email(message, addresses, origin)
        return message.with_env(self.env)

    def _edi_send_notice_email(self, message, addresses, origin):
        """Send the one email of a notice, to ``addresses`` only.

        Built by hand rather than through the follower-based notification so
        that nobody else can receive it, with the note's own ``Message-Id``
        (a ``mail.mail`` takes it from its ``mail_message_id``).
        """
        # sudo: creating mail.mail needs the mail server rights
        base_values = self.sudo()._notify_by_email_get_base_mail_values(
            message, additional_values={"auto_delete": True}
        )
        references = base_values.get("references", "").split()
        headers = ast.literal_eval(base_values.get("headers") or "{}")
        if origin.get("message_id"):
            # oldest first, as RFC 5322 wants: the inbound email, whatever the
            # order's own thread contributed, then this note
            references = [origin["message_id"]] + [
                ref for ref in references if ref != origin["message_id"]
            ]
            headers["In-Reply-To"] = origin["message_id"]
        mail = (
            self.env["mail.mail"]
            .sudo()
            .create(
                {
                    **base_values,
                    "references": " ".join(references),
                    "headers": repr(headers),
                    "email_to": ", ".join(addresses),
                    "body_html": self._edi_absolute_links(message.sudo().body),
                    "state": "outgoing",
                }
            )
        )
        # as Odoo does for its own notifications (see `_notify_thread_by_email`)
        if self.env.context.get("mail_notify_force_send", True) and not self.pool._init:
            mail.send_after_commit()
        return mail

    @api.model
    def _edi_absolute_links(self, body):
        """``body`` with the links to records (``_get_html_link()`` renders
        them as ``href="#"`` plus ``data-oe-model``/``data-oe-id``, which only
        work inside the web client) pointing at their form view, so that they
        work in an email too (relative links are made absolute when it is
        sent).
        """
        if not body or "data-oe-model" not in body:
            return body
        root = lxml_html.fragment_fromstring(str(body), create_parent="div")
        for link in root.xpath("//a[@data-oe-model and @data-oe-id]"):
            link.set(
                "href", f"/odoo/{link.get('data-oe-model')}/{link.get('data-oe-id')}"
            )
        # strip the wrapping <div>
        return Markup(lxml_html.tostring(root, encoding="unicode")[5:-6])

    def _edi_notice_still_needed(self):
        """Whether an *outstanding* notice about this order still calls for
        somebody's attention. Consulted by `_edi_post_notice()` before the
        inbox is notified. Override to say no once the order is already
        taken care of (e.g. matched to a repair order); `_edi_clear_notices()`
        then clears the ones already posted.
        """
        self.ensure_one()
        return True

    def _edi_outstanding_notices(self):
        """The outstanding notices (see `_edi_post_notice()`) about these
        orders, as a sudo ``mail.message`` recordset. Extend to include
        notices posted elsewhere on the orders' behalf (e.g. on a related
        record's chatter), which `_edi_clear_notices()` then clears too.
        """
        # sudo: a technical search, nothing is returned to the user
        return (
            self.env["mail.message"]
            .sudo()
            .search(
                [
                    ("model", "=", self._name),
                    ("res_id", "in", self.ids),
                    ("edi_notice_outstanding", "=", True),
                ]
            )
        )

    def _edi_clear_notices(self):
        """Mark the inbox notifications of the outstanding notices of these
        orders as read, for every user, and refresh their inbox counters.

        Idempotent and quiet: it sends no email and creates no notification,
        and the notices stay in the chatter. Runs as sudo (the caller is
        generally not the recipient) but only touches the ``is_read`` flag
        of inbox notifications of notices flagged as outstanding on these
        very orders (`_edi_outstanding_notices()`).

        :return: the ``mail.message`` notices concerned
        """
        messages = self._edi_outstanding_notices()
        notifications = (
            self.env["mail.notification"]
            .sudo()
            .search(
                [
                    ("mail_message_id", "in", messages.ids),
                    ("notification_type", "=", "inbox"),
                    ("is_read", "=", False),
                ]
            )
        )
        if not notifications:
            return messages
        notifications.write({"is_read": True})
        for user in notifications.res_partner_id.user_ids:
            # same bus message as `mail.message.set_message_done()`
            user._bus_send(
                "mail.message/mark_as_read",
                {
                    "message_ids": notifications.filtered(
                        lambda n, user=user: n.res_partner_id == user.partner_id
                    ).mail_message_id.ids,
                    "needaction_inbox_counter": user.partner_id._get_needaction_count(),
                },
            )
        return messages

    # ------------------------------------------------------------
    # WHO TO TELL
    # ------------------------------------------------------------

    def _edi_exchange_record(self):
        """The (latest) exchange record that created this order, if any."""
        self.ensure_one()
        # sudo: whoever triggers the import (mail gateway, cron, a manager
        # re-processing) is not necessarily allowed to read exchange records.
        return (
            self.env["edi.exchange.record"]
            .sudo()
            .search(
                [("model", "=", self._name), ("res_id", "=", self.id)],
                order="id desc",
                limit=1,
            )
        )

    def _edi_originating_email(self):
        """The inbound email that produced this order, as a dict with the
        ``message_id`` and ``subject`` keys (``{}`` when there is none, e.g.
        the order came from a manually uploaded PDF).

        The Message-Id/subject are read from the exchange record itself
        (``inbound_message_id``/``inbound_subject``, stored by
        ``import_from_email`` when the mail gateway creates it). That is what
        makes this work with ``quick_exec``, where the order is processed
        before the gateway has posted the inbound ``mail.message``. Exchange
        records that predate those fields fall back to the first inbound
        ``mail.message`` posted on the record.
        """
        self.ensure_one()
        exchange = self._edi_exchange_record()
        if not exchange:
            return {}
        message_id, subject = exchange.inbound_message_id, exchange.inbound_subject
        if not message_id:
            inbound = (
                self.env["mail.message"]
                .sudo()
                .search(
                    [
                        ("model", "=", exchange._name),
                        ("res_id", "=", exchange.id),
                        ("message_type", "=", "email"),
                        ("message_id", "!=", False),
                    ],
                    order="id asc",
                    limit=1,
                )
            )
            message_id, subject = inbound.message_id, inbound.subject
        if not message_id:
            return {}
        return {"message_id": message_id, "subject": subject or ""}

    def _edi_reply_addresses(self):
        """The email addresses a notice goes to, as normalized strings: the
        ones ``import_from_email`` stored on the exchange record
        (``inbound_reply_to``), minus

        - any address of the order's vendor (its commercial partner and their
          contacts): a vendor that wrote to the alias directly must not get
          our notices either;
        - any address that is not a known shop-side one (see
          `_edi_reply_address_allowed()`): the stored addresses come from
          headers whoever can write to the mail alias controls.

        Empty when unknown.
        """
        self.ensure_one()
        exchange = self._edi_exchange_record()
        stored = exchange.inbound_reply_to if exchange else False
        if not stored:
            return []
        # sudo: only email addresses are read, to be left out
        vendor = self.sudo().partner_id.commercial_partner_id
        excluded = {
            email_normalize(partner.email)
            for partner in vendor | vendor.child_ids | self.sudo().partner_id
            if partner.email
        }
        allowed = self._edi_reply_address_allowed()
        return [
            address
            for address in dict.fromkeys(
                email_normalize(a) for a in stored.split(",") if a.strip()
            )
            if address and address not in excluded and allowed(address)
        ]

    @api.model
    def _edi_reply_address_allowed(self):
        """A predicate telling whether a notice may be emailed to an address.

        The reply addresses are read from the headers of an inbound email, so
        anybody who can write to the mail alias chooses them. A notice (and
        the "Confirm Match" link it can carry) is only ever emailed to

        - the email of an internal user or of a company of this database, and
        - what Settings > Purchase > "Allowed Reply Addresses" lists: email
          addresses (``orders@shop.example``) and domains (``@shop.example``),
          separated by commas, spaces or new lines. The shop mailbox the
          forwarding rule belongs to is usually named there.
        """
        # sudo: only email addresses are read, to be compared with
        param = self.env["ir.config_parameter"].sudo().get_param(REPLY_ALLOWED_PARAM)
        entries = {
            entry.strip().lower()
            for entry in re.split(r"[\s,;]+", param or "")
            if entry.strip()
        }
        known = {
            email_normalize(email)
            for email in (
                self.env["res.users"]
                .sudo()
                .search([("share", "=", False)])
                .partner_id.mapped("email")
                + self.env["res.company"].sudo().search([]).mapped("email")
            )
            if email
        }
        addresses = {entry for entry in entries if "@" in entry[1:]} | known
        domains = {entry.lstrip("@") for entry in entries if "@" not in entry[1:]}

        def allowed(address):
            return address in addresses or address.partition("@")[2] in domains

        return allowed

    def _edi_notify_partners(self):
        """The res.partner recordset to notify: every user in the group
        configured at Settings > Purchase (falling back to the built-in
        Purchase Administrator group if nothing's been configured yet).
        """
        # sudo: the configuration and the group's members are read on behalf
        # of an import that may run as a user who cannot read them; only the
        # partners of the group's (active) users are returned.
        param = self.env["ir.config_parameter"].sudo().get_param(NOTIFY_GROUP_PARAM)
        groups = self.env["res.groups"].sudo()
        group = groups.browse(int(param)).exists() if param else groups
        if not group:
            group = self.env.ref(
                "purchase.group_purchase_manager", raise_if_not_found=False
            )
        return self.env["res.partner"].browse(
            group.sudo().users.partner_id.ids if group else []
        )

    # ------------------------------------------------------------
    # NOTIFICATION OVERRIDES
    # ------------------------------------------------------------

    def message_post(self, **kwargs):
        """The answer of the shop mailbox to a notice email, which the mail
        gateway posts here as a discussion message (``mail.mt_comment``), is
        an internal note: the vendor follows the order's discussions, and our
        internal conversation must not be mailed to it.
        """
        parent_id = kwargs.get("parent_id")
        if parent_id and kwargs.get("message_type") == "email":
            notice = self.env.ref(NOTICE_SUBTYPE, raise_if_not_found=False)
            parent = self.env["mail.message"].sudo().browse(parent_id)
            if notice and parent.subtype_id == notice:
                kwargs.pop("subtype_xmlid", None)
                kwargs["subtype_id"] = self.env["ir.model.data"]._xmlid_to_res_id(
                    "mail.mt_note"
                )
        return super().message_post(**kwargs)

    def _get_notify_valid_parameters(self):
        return super()._get_notify_valid_parameters() | {"edi_notice_mode"}

    def _notify_get_recipients(self, message, msg_vals, **kwargs):
        """``edi_notice_mode`` (a `message_post()` notification parameter set by
        `_edi_post_notice()`):

        - ``"inbox"``: only internal users are notified, and in their inbox,
          whatever their notification preference (a partner without a user,
          or a portal user, gets nothing);
        - ``"silent"``: nobody is notified.
        """
        recipients = super()._notify_get_recipients(message, msg_vals, **kwargs)
        mode = kwargs.get("edi_notice_mode")
        if not mode:
            return recipients
        if mode == "silent":
            return []
        return [
            {**recipient, "notif": "inbox"}
            for recipient in recipients
            if recipient.get("uid") and not recipient.get("ushare")
        ]
