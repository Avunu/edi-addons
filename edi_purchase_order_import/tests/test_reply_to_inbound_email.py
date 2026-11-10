# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import ast
from unittest import mock

from markupsafe import Markup

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.edi_purchase_order_import.models.purchase_order import (
    REPLY_ALLOWED_PARAM,
)

ALIAS_NAME = "edi-orders"
ALIAS_DOMAIN = "edi-notice-test.example"
ALIAS_EMAIL = f"{ALIAS_NAME}@{ALIAS_DOMAIN}"
SHOP_EMAIL = "orders@shop.example"
VENDOR_EMAIL = "sales@vendor.example"
SUBJECT = "Order confirmation ORD-1"

RAW_EMAIL = """\
Delivered-To: {alias}
Message-Id: {message_id}
Subject: {subject}
From: {sender}
To: {to}
{extra_headers}Date: Mon, 09 Nov 2026 10:00:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

Order #: ORD-1
Vendor: EDI NOTICE TEST VENDOR
"""

GMAIL_FORWARD_HEADERS = (
    f"X-Forwarded-For: {SHOP_EMAIL} {ALIAS_EMAIL}\nX-Forwarded-To: {ALIAS_EMAIL}\n"
)

RAW_REPLY = """\
Message-Id: <shop-reply-{n}@shop.example>
In-Reply-To: {notice_id}
References: {inbound_id} {notice_id}
Subject: Re: {subject}
From: Shop Orders <{shop_email}>
To: {reply_to}
Date: Mon, 09 Nov 2026 11:00:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

Thanks, noted.
"""


@tagged("post_install", "-at_install")
class TestEdiNotice(TransactionCase):
    """The notices of an EDI-imported purchase order: internal note, inbox
    notification for the notify group (never an email), and one threaded email
    to the shop mailbox that forwarded the vendor's email (never the vendor).

    Inbound emails go through the real mail gateway
    (`mail.thread.message_process()`) via a real `mail.alias` onto
    `edi.exchange.record`, so the headers a mail server really adds and the
    `quick_exec` ordering (the order is processed *before* the gateway posts
    the inbound message) are exercised for real.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # leave the emails queued ("outgoing") instead of sending - and, being
        # auto_delete, deleting - them on the spot
        cls.env = cls.env(context=dict(cls.env.context, mail_notify_force_send=False))
        ref = cls.env.ref
        cls.vendor = cls.env["res.partner"].create(
            {"name": "EDI NOTICE TEST VENDOR", "email": VENDOR_EMAIL}
        )
        # A group of its own, so only the users below are notified
        cls.group = cls.env["res.groups"].create({"name": "EDI notice test notify"})
        cls.manager = cls.env["res.users"].create(
            {
                "name": "EDI Notice Manager",
                "login": "edi_notice_manager",
                "email": "edi.notice.manager@example.com",
                "notification_type": "email",
                "groups_id": [(6, 0, [ref("base.group_user").id, cls.group.id])],
            }
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "edi_purchase_order_import.notify_group_id", cls.group.id
        )
        # the shop mailboxes notices may be emailed to
        cls.env["ir.config_parameter"].sudo().set_param(
            REPLY_ALLOWED_PARAM, "@shop.example"
        )
        # an internal user who follows the order (emails by preference) and a
        # portal user: neither may get anything
        cls.follower = cls.env["res.users"].create(
            {
                "name": "EDI Notice Follower",
                "login": "edi_notice_follower",
                "email": "edi.notice.follower@example.com",
                "notification_type": "email",
                "groups_id": [(6, 0, [ref("base.group_user").id])],
            }
        )
        cls.portal = cls.env["res.users"].create(
            {
                "name": "EDI Notice Portal",
                "login": "edi_notice_portal",
                "email": "edi.notice.portal@example.com",
                "groups_id": [(6, 0, [ref("base.group_portal").id])],
            }
        )
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "EDI notice test template",
                "extraction_mode": "plaintext",
                "model_id": ref("purchase.model_purchase_order").id,
                "auto_detect_pattern": "Order #:",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "related_model": "header",
                            "field_id": ref(
                                "purchase.field_purchase_order__partner_id"
                            ).id,
                            "pattern": "Vendor: (.*)",
                            "search_field_id": ref("base.field_res_partner__name").id,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 11,
                            "related_model": "header",
                            "field_id": ref(
                                "purchase.field_purchase_order__partner_ref"
                            ).id,
                            "pattern": "Order #: (.*)",
                        },
                    ),
                ],
            }
        )
        backend_type = cls.env["edi.backend.type"].create(
            {"name": "EDI notice test type", "code": "edi_notice_test_backend_type"}
        )
        cls.backend = cls.env["edi.backend"].create(
            {"name": "EDI notice test backend", "backend_type_id": backend_type.id}
        )
        cls.exchange_type = cls.env["edi.exchange.type"].create(
            {
                "name": "EDI notice test PO",
                "code": "edi_notice_test_po",
                "direction": "input",
                "backend_type_id": backend_type.id,
                "backend_id": cls.backend.id,
                "process_model_id": cls.env["ir.model"]
                ._get("edi.input.process.template")
                .id,
                "import_template_id": cls.template.id,
                "quick_exec": True,
            }
        )
        domain = cls.env["mail.alias.domain"].create({"name": ALIAS_DOMAIN})
        cls.env["mail.alias"].create(
            {
                "alias_name": ALIAS_NAME,
                "alias_domain_id": domain.id,
                "alias_model_id": cls.env["ir.model"]._get("edi.exchange.record").id,
                "alias_contact": "everyone",
                "alias_defaults": repr(
                    {
                        "backend_id": cls.backend.id,
                        "type_code": cls.exchange_type.code,
                    }
                ),
            }
        )

    # -- helpers -----------------------------------------------------------

    def _receive_email(
        self,
        n,
        sender=f"Vendor Sales <{VENDOR_EMAIL}>",
        to=SHOP_EMAIL,
        extra_headers=GMAIL_FORWARD_HEADERS,
        subject=SUBJECT,
    ):
        """Feed an inbound email through the mail gateway; return the
        exchange record it created."""
        before = self.env["edi.exchange.record"].search([]).ids
        self.env["mail.thread"].message_process(
            None,
            RAW_EMAIL.format(
                alias=ALIAS_EMAIL,
                message_id=f"<inbound-order-{n}@vendor.example>",
                subject=subject,
                sender=sender,
                to=to,
                extra_headers=extra_headers,
            ),
        )
        exchange = self.env["edi.exchange.record"].search([("id", "not in", before)])
        self.assertEqual(len(exchange), 1)
        if exchange.type_id.quick_exec:
            self.assertEqual(
                exchange.edi_exchange_state,
                "input_processed",
                exchange.exchange_error_traceback or exchange.exchange_error,
            )
        return exchange

    def _receive_with_followers(self, n, **kwargs):
        """`_receive_email()`, with the vendor and other people following the
        order before it is confirmed and notified (as they would be)."""
        original = self.env.registry["purchase.order"]._edi_confirm_and_notify
        test = self

        def subscribe_then_notify(order):
            order.message_subscribe(
                partner_ids=(
                    test.vendor | test.follower.partner_id | test.portal.partner_id
                ).ids,
            )
            # even explicitly subscribed to the notice subtype
            order.message_follower_ids.filtered(
                lambda f: (
                    f.partner_id in test.follower.partner_id | test.portal.partner_id
                )
            ).sudo().subtype_ids |= test.env.ref(
                "edi_purchase_order_import.mt_edi_notice"
            )
            return original(order)

        with mock.patch.object(
            self.env.registry["purchase.order"],
            "_edi_confirm_and_notify",
            subscribe_then_notify,
        ):
            return self._receive_email(n, **kwargs)

    def _inbound_message(self, exchange):
        message = self.env["mail.message"].search(
            [
                ("model", "=", "edi.exchange.record"),
                ("res_id", "=", exchange.id),
                ("message_id", "=", exchange.inbound_message_id),
            ]
        )
        self.assertEqual(len(message), 1)
        return message

    def _notices(self, order):
        return order.message_ids.filtered(
            lambda m: (
                m.subtype_id == self.env.ref("edi_purchase_order_import.mt_edi_notice")
            )
        ).sorted("id")

    def _notice(self, order):
        notice = self._notices(order)
        self.assertEqual(len(notice), 1)
        return notice

    def _mails(self, message):
        return self.env["mail.mail"].search([("mail_message_id", "=", message.id)])

    def _inbox(self, user, message):
        return self.env["mail.notification"].search(
            [
                ("mail_message_id", "=", message.id),
                ("res_partner_id", "=", user.partner_id.id),
            ]
        )

    def _rfc822(self, mail):
        values = mail._prepare_outgoing_list()[0]
        return self.env["ir.mail_server"].build_email(
            email_from=values["email_from"],
            email_to=values["email_to"],
            subject=values["subject"],
            body=values["body"],
            references=values["references"],
            message_id=values["message_id"],
            headers=values["headers"],
        )

    def _all_mail_to(self, partner_or_email):
        mails = self.env["mail.mail"].search([])
        if isinstance(partner_or_email, str):
            return mails.filtered(lambda m: partner_or_email in (m.email_to or ""))
        return mails.filtered(lambda m: partner_or_email in m.recipient_ids)

    # -- tests -------------------------------------------------------------

    def test_gmail_forward_replies_to_the_shop_mailbox_only(self):
        mails_before = self.env["mail.mail"].search([]).ids
        exchange = self._receive_with_followers(1)
        # the shop address, not the vendor, not the Odoo alias
        self.assertEqual(exchange.inbound_reply_to, SHOP_EMAIL)
        order = exchange.record
        self.assertEqual(order._name, "purchase.order")
        self.assertEqual(order.state, "purchase")
        # the vendor is a follower with an email address, as are others
        self.assertIn(self.vendor, order.message_partner_ids)
        self.assertIn(self.follower.partner_id, order.message_partner_ids)

        notice = self._notice(order)
        self.assertEqual(notice.subject, "Re: " + SUBJECT)
        self.assertTrue(notice.subtype_id.internal)
        self.assertTrue(notice.edi_notice_outstanding)
        # held back until the inbound email is on the chatter
        self.assertGreater(notice.id, self._inbound_message(exchange).id)
        self.assertFalse(exchange.edi_pending_notices)

        # exactly one email, to the shop mailbox only
        mails = self._mails(notice)
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.email_to, SHOP_EMAIL)
        self.assertFalse(mails.recipient_ids)
        self.assertFalse(mails.email_cc)
        # and no other email went out at all from this order
        new_mails = self.env["mail.mail"].search([("id", "not in", mails_before)])
        self.assertEqual(new_mails, mails)
        for nobody in (
            self.vendor,
            self.follower.partner_id,
            self.portal.partner_id,
            self.manager.partner_id,
        ):
            self.assertFalse(self._all_mail_to(nobody))
        self.assertFalse(self._all_mail_to(VENDOR_EMAIL))

        # threaded as a reply, with the note's own Message-Id
        rfc822 = self._rfc822(mails)
        self.assertEqual(rfc822["Subject"], "Re: " + SUBJECT)
        self.assertEqual(rfc822["In-Reply-To"], exchange.inbound_message_id)
        references = rfc822["References"].split()
        self.assertEqual(references[0], exchange.inbound_message_id)
        self.assertEqual(references[-1], notice.message_id)
        self.assertEqual(rfc822["Message-Id"], notice.message_id)
        self.assertEqual(mails.message_id, notice.message_id)
        self.assertEqual(
            ast.literal_eval(mails.headers)["In-Reply-To"],
            exchange.inbound_message_id,
        )
        self.assertEqual(mails.state, "outgoing")

    def test_group_gets_the_inbox_notification_but_no_email(self):
        exchange = self._receive_with_followers(2)
        notice = self._notice(exchange.record)
        # notification preference is "email", yet inbox only
        self.assertEqual(self.manager.notification_type, "email")
        notifications = self._inbox(self.manager, notice)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications.notification_type, "inbox")
        self.assertFalse(notifications.is_read)
        self.assertEqual(self.manager.partner_id._get_needaction_count(), 1)
        # internal follower subscribed to the notice subtype: inbox as well,
        # still no email; the portal follower gets nothing at all
        self.assertEqual(self._inbox(self.follower, notice).notification_type, "inbox")
        self.assertFalse(self._inbox(self.portal, notice))
        self.assertFalse(
            self.env["mail.notification"].search(
                [
                    ("mail_message_id", "=", notice.id),
                    ("notification_type", "=", "email"),
                ]
            )
        )

    def test_manual_forward_replies_to_the_forwarder(self):
        exchange = self._receive_email(
            3,
            sender="Shop Person <person@shop.example>",
            to=ALIAS_EMAIL,
            extra_headers="",
            subject="Fwd: " + SUBJECT,
        )
        self.assertEqual(exchange.inbound_reply_to, "person@shop.example")
        notice = self._notice(exchange.record)
        self.assertEqual(notice.subject, "Re: Fwd: " + SUBJECT)
        mails = self._mails(notice)
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.email_to, "person@shop.example")

    def test_existing_re_prefix_is_not_doubled(self):
        exchange = self._receive_email(4, subject="RE:  Order  ORD-4")
        self.assertEqual(self._notice(exchange.record).subject, "RE: Order ORD-4")

    def test_vendor_writing_to_the_alias_is_not_answered(self):
        # no forwarding: only the vendor's own address is known (as the
        # sender, the fallback), and the vendor must never be emailed
        exchange = self._receive_email(
            5, to=ALIAS_EMAIL, extra_headers="", sender=VENDOR_EMAIL
        )
        self.assertEqual(exchange.inbound_reply_to, VENDOR_EMAIL)
        order = exchange.record
        self.assertEqual(order._edi_reply_addresses(), [])
        notice = self._notice(order)
        self.assertFalse(self._mails(notice))
        self.assertFalse(self._all_mail_to(VENDOR_EMAIL))
        self.assertTrue(self._inbox(self.manager, notice))

    def test_no_reply_addresses_sends_nothing_but_notifies_the_inbox(self):
        exchange = self._receive_email(
            6,
            sender="Vendor <no-reply@vendor.example>",
            to=ALIAS_EMAIL,
            extra_headers="",
        )
        self.assertFalse(exchange.inbound_reply_to)
        order = exchange.record
        self.assertEqual(order.state, "purchase")
        notice = self._notice(order)
        self.assertFalse(self._mails(notice))
        self.assertEqual(self._inbox(self.manager, notice).notification_type, "inbox")
        self.assertFalse(self._all_mail_to(self.manager.partner_id))

    def test_order_without_email_origin(self):
        # e.g. created from a manually uploaded PDF
        order = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        self.assertEqual(order._edi_originating_email(), {})
        order._edi_confirm_and_notify()
        self.assertEqual(order.state, "purchase")
        notice = self._notice(order)
        self.assertFalse(notice.subject and notice.subject.startswith("Re:"))
        self.assertFalse(self._mails(notice))
        self.assertEqual(self._inbox(self.manager, notice).notification_type, "inbox")
        # same through an exchange record that does not come from an email
        self.env["edi.exchange.record"].with_context(edi__skip_quick_exec=True).create(
            {
                "backend_id": self.backend.id,
                "type_id": self.exchange_type.id,
                "model": "purchase.order",
                "res_id": order.id,
            }
        )
        self.assertEqual(order._edi_reply_addresses(), [])
        self.assertFalse(self._mails(order._edi_post_notice("again")))

    def test_post_notice_options(self):
        exchange = self._receive_email(7)
        order = exchange.record
        # email=False: note + inbox only
        note = order._edi_post_notice("Only here", email=False, outstanding=False)
        self.assertFalse(self._mails(note))
        self.assertTrue(self._inbox(self.manager, note))
        self.assertFalse(note.edi_notice_outstanding)
        self.assertEqual(note.subject, "Re: " + SUBJECT)
        # a later one: immediate, emailed once, own subject honoured
        later = order._edi_post_notice(
            "Another thing", subject="Different", author_id=self.follower.partner_id.id
        )
        self.assertEqual(later.subject, "Different")
        self.assertEqual(later.author_id, self.follower.partner_id)
        mails = self._mails(later)
        self.assertEqual(mails.mapped("email_to"), [SHOP_EMAIL])
        self.assertEqual(
            self._rfc822(mails)["In-Reply-To"], exchange.inbound_message_id
        )
        self.assertEqual(
            self._rfc822(mails)["References"].split()[0], exchange.inbound_message_id
        )

    def test_notice_posted_while_the_inbound_email_is_pending_is_deferred(self):
        original = self.env.registry["purchase.order"]._edi_confirm_and_notify
        seen = {}

        def spy(order):
            original(order)
            # quick_exec: the inbound message is not there yet, so both
            # notices were held back, whatever is posted in between
            seen["first"] = order._edi_post_notice("Second notice", outstanding=False)
            seen["silent"] = order._edi_post_notice("No email", email=False)
            seen["notices"] = len(order.message_ids.filtered("subtype_id"))

        with mock.patch.object(
            self.env.registry["purchase.order"], "_edi_confirm_and_notify", spy
        ):
            exchange = self._receive_email(8)
        self.assertFalse(seen["first"])
        # the one without an email is posted at once
        self.assertTrue(seen["silent"])
        order = exchange.record
        inbound = self._inbound_message(exchange)
        notices = self._notices(order)
        self.assertEqual(len(notices), 3)
        deferred = notices.filtered(lambda m: self._mails(m))
        self.assertEqual(len(deferred), 2)
        for notice in deferred:
            self.assertGreater(notice.id, inbound.id)
        self.assertFalse(exchange.edi_pending_notices)

    def test_reply_from_the_shop_mailbox_lands_on_the_purchase_order(self):
        exchange = self._receive_email(9)
        order = exchange.record
        notice = self._notice(order)
        exchanges = self.env["edi.exchange.record"].search_count([])
        self.env["mail.thread"].message_process(
            None,
            RAW_REPLY.format(
                n=9,
                notice_id=notice.message_id,
                inbound_id=exchange.inbound_message_id,
                subject=SUBJECT,
                shop_email=SHOP_EMAIL,
                reply_to=notice.reply_to or ALIAS_EMAIL,
            ),
        )
        reply = self.env["mail.message"].search(
            [("message_id", "=", "<shop-reply-9@shop.example>")]
        )
        self.assertEqual((reply.model, reply.res_id), ("purchase.order", order.id))
        self.assertEqual(self.env["edi.exchange.record"].search_count([]), exchanges)

    def test_clear_notices_marks_the_inbox_read_for_everybody(self):
        exchange = self._receive_with_followers(10)
        order = exchange.record
        notice = self._notice(order)
        other = order._edi_post_notice("Not clearable", email=False, outstanding=False)
        for message in (notice, other):
            self.assertFalse(self._inbox(self.manager, message).is_read)
        self.assertEqual(self.manager.partner_id._get_needaction_count(), 2)
        self.assertEqual(self.follower.partner_id._get_needaction_count(), 2)

        # a user who is not the recipient, with no business with purchases
        outsider = self.env["res.users"].create(
            {
                "name": "EDI Notice Outsider",
                "login": "edi_notice_outsider",
                "email": "outsider@example.com",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        cleared = order.with_user(outsider)._edi_clear_notices()
        self.assertEqual(cleared, notice)
        self.assertTrue(self._inbox(self.manager, notice).is_read)
        self.assertTrue(self._inbox(self.follower, notice).is_read)
        # the other one was not an outstanding notice
        self.assertFalse(self._inbox(self.manager, other).is_read)
        self.assertEqual(self.manager.partner_id._get_needaction_count(), 1)
        self.assertEqual(self.follower.partner_id._get_needaction_count(), 1)
        # idempotent
        order._edi_clear_notices()
        self.assertEqual(self.manager.partner_id._get_needaction_count(), 1)

    def test_clear_notices_tells_the_client_through_the_bus(self):
        order = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        order._edi_post_notice("Look", email=False)
        with mock.patch(
            "odoo.addons.bus.models.bus_listener_mixin.BusListenerMixin._bus_send"
        ) as bus_send:
            order._edi_clear_notices()
        self.assertTrue(
            [
                call
                for call in bus_send.call_args_list
                if call.args[0] == "mail.message/mark_as_read"
                and call.args[1]["needaction_inbox_counter"] == 0
            ]
        )

    def test_hook_can_say_the_notice_is_no_longer_needed(self):
        calls = []

        def not_needed(order):
            calls.append(order.id)
            return False

        with mock.patch.object(
            self.env.registry["purchase.order"], "_edi_notice_still_needed", not_needed
        ):
            exchange = self._receive_email(11)
        order = exchange.record
        # consulted when the (deferred) notice is actually posted
        self.assertEqual(calls, [order.id])
        notice = self._notice(order)
        # posted and emailed all the same, but nobody has anything to do
        self.assertEqual(self._mails(notice).email_to, SHOP_EMAIL)
        self.assertFalse(self._inbox(self.manager, notice))
        self.assertFalse(notice.edi_notice_outstanding)
        self.assertEqual(self.manager.partner_id._get_needaction_count(), 0)
        # not consulted for a notice that is not outstanding
        calls.clear()
        with mock.patch.object(
            self.env.registry["purchase.order"], "_edi_notice_still_needed", not_needed
        ):
            note = order._edi_post_notice("Info", email=False, outstanding=False)
        self.assertEqual(calls, [])
        self.assertTrue(self._inbox(self.manager, note))
        # default: still needed
        self.assertTrue(order._edi_notice_still_needed())

    def test_runs_as_a_low_privilege_user(self):
        # the gateway may run as a portal-ish alias owner: the notice is
        # posted anyway, without widening what that user can read
        order = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        notice = order.with_user(self.portal)._edi_post_notice("From a portal user")
        self.assertTrue(notice.sudo().edi_notice_outstanding)
        self.assertEqual(notice.sudo().author_id, self.env.ref("base.partner_root"))
        self.assertTrue(self._inbox(self.manager, notice.sudo()))
        self.assertEqual(
            order.with_user(self.portal)._edi_notify_partners(),
            self.manager.partner_id,
        )
        # the portal user can neither read the order nor its notices
        self.assertFalse(
            self.env["mail.message"]
            .with_user(self.portal)
            .search([("id", "=", notice.id)])
        )

    def test_confirmation_is_idempotent(self):
        exchange = self._receive_email(12)
        order = exchange.record
        order._edi_confirm_and_notify()
        self.assertEqual(order.state, "purchase")

    # -- where the notice may go ----------------------------------------------

    def test_gmail_forward_keeps_the_shop_mailbox_of_the_second_delivered_to(self):
        # A Gmail forwarding rule keeps the shop mailbox's own Delivered-To
        # (lower in the header block); only the top-most one is the Odoo side.
        exchange = self._receive_email(
            13,
            to="Orders <orders@shop.example>",
            extra_headers=(
                GMAIL_FORWARD_HEADERS + f"Delivered-To: {SHOP_EMAIL}\n"
                f"X-Original-To: {SHOP_EMAIL}\n"
            ),
        )
        self.assertEqual(exchange.inbound_reply_to, SHOP_EMAIL)
        notice = self._notice(exchange.record)
        self.assertEqual(self._mails(notice).email_to, SHOP_EMAIL)

    def test_a_colleague_of_the_vendor_in_to_is_not_emailed(self):
        exchange = self._receive_email(
            14,
            to=f"{SHOP_EMAIL}, accounting@vendor.example, big@customer.example",
            extra_headers="",
        )
        # the vendor's colleague is out at intake; the third party is let
        # through by intake but the allowed addresses keep it out
        self.assertIn(SHOP_EMAIL, exchange.inbound_reply_to)
        self.assertNotIn("accounting@vendor.example", exchange.inbound_reply_to)
        self.assertEqual(exchange.record._edi_reply_addresses(), [SHOP_EMAIL])
        self.assertEqual(
            self._mails(self._notice(exchange.record)).email_to, SHOP_EMAIL
        )

    def test_addresses_nobody_vouched_for_are_never_emailed(self):
        # whoever can write to the alias chooses To and X-Forwarded-For
        evil = ", ".join(f"v{i}@evil.example" for i in range(20))
        exchange = self._receive_email(
            15,
            to=f"{evil}, {SHOP_EMAIL}",
            sender="Somebody <somebody@elsewhere.example>",
            extra_headers="",
        )
        self.assertLessEqual(len(exchange.inbound_reply_to.split(",")), 5)
        order = exchange.record
        self.assertEqual(order._edi_reply_addresses(), [])
        notice = self._notice(order)
        self.assertFalse(self._mails(notice))
        self.assertFalse(self._all_mail_to("evil.example"))
        # the inbox notification still happens
        self.assertTrue(self._inbox(self.manager, notice))

    def test_allowed_addresses_are_addresses_domains_and_known_emails(self):
        order = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        params = self.env["ir.config_parameter"].sudo()
        params.set_param(REPLY_ALLOWED_PARAM, "a@x.example, @y.example\nz.example")
        allowed = order._edi_reply_address_allowed()
        for address in ("a@x.example", "b@y.example", "c@z.example"):
            self.assertTrue(allowed(address), address)
        for address in ("b@x.example", "a@sub.y.example", "c@other.example"):
            self.assertFalse(allowed(address), address)
        # internal users' and companies' emails are always allowed, portal
        # users' are not
        self.assertTrue(allowed(self.manager.partner_id.email))
        self.env.company.sudo().email = "shop@company.example"
        allowed = order._edi_reply_address_allowed()
        self.assertTrue(allowed("shop@company.example"))
        self.assertFalse(allowed(self.portal.partner_id.email))
        params.set_param(REPLY_ALLOWED_PARAM, False)
        allowed = order._edi_reply_address_allowed()
        self.assertFalse(allowed(SHOP_EMAIL))
        self.assertTrue(allowed(self.manager.partner_id.email))

    def test_internal_user_mailbox_is_emailed_without_any_setting(self):
        self.env["ir.config_parameter"].sudo().set_param(REPLY_ALLOWED_PARAM, False)
        exchange = self._receive_email(
            16,
            to=self.manager.partner_id.email,
            extra_headers="",
        )
        notice = self._notice(exchange.record)
        self.assertEqual(self._mails(notice).email_to, self.manager.partner_id.email)

    # -- the emailed copy --------------------------------------------------------

    def test_emailed_links_to_records_are_absolute(self):
        exchange = self._receive_email(17)
        order = exchange.record
        notice = order._edi_post_notice(
            Markup("<p>See %s</p>") % order._get_html_link(), outstanding=False
        )
        mail = self._mails(notice)
        self.assertEqual(len(mail), 1)
        body = mail._prepare_outgoing_body()
        base_url = order.get_base_url()
        self.assertIn(f'href="{base_url}/odoo/purchase.order/{order.id}"', body)
        self.assertNotIn('href="#"', body)
        # the note in the chatter is untouched
        self.assertIn('href="#"', notice.body)

    # -- the shop's answer ----------------------------------------------------

    def test_the_shops_answer_is_an_internal_note_the_vendor_does_not_get(self):
        exchange = self._receive_with_followers(18)
        order = exchange.record
        notice = self._notice(order)
        self.assertIn(self.vendor, order.message_partner_ids)
        self.env["mail.thread"].message_process(
            None,
            RAW_REPLY.format(
                n=18,
                notice_id=notice.message_id,
                inbound_id=exchange.inbound_message_id,
                subject=SUBJECT,
                shop_email=SHOP_EMAIL,
                reply_to=notice.reply_to or ALIAS_EMAIL,
            ),
        )
        reply = self.env["mail.message"].search(
            [("message_id", "=", "<shop-reply-18@shop.example>")]
        )
        self.assertEqual((reply.model, reply.res_id), ("purchase.order", order.id))
        self.assertEqual(reply.subtype_id, self.env.ref("mail.mt_note"))
        self.assertFalse(self._all_mail_to(self.vendor))
        self.assertFalse(self._all_mail_to(VENDOR_EMAIL))
        self.assertFalse(self._all_mail_to(self.portal.partner_id))
        # a plain discussion message on the order still reaches the vendor
        order.message_post(body="Hello", subtype_xmlid="mail.mt_comment")
        self.assertTrue(self._all_mail_to(self.vendor))

    # -- email whose References collide with an earlier exchange ---------------

    def test_an_email_replying_to_an_earlier_exchange_is_a_new_exchange(self):
        first = self._receive_email(19)
        second_before = self.env["purchase.order"].search_count([])
        second = self._receive_email(
            20,
            extra_headers=(
                GMAIL_FORWARD_HEADERS
                + f"In-Reply-To: {first.inbound_message_id}\n"
                + f"References: {first.inbound_message_id}\n"
            ),
        )
        self.assertNotEqual(first, second)
        self.assertEqual(self.env["purchase.order"].search_count([]), second_before + 1)
        # the routing headers reached the new exchange all the same
        self.assertEqual(second.inbound_reply_to, SHOP_EMAIL)
        # ... and its notice was released when the email was posted (on the
        # earlier exchange, which is where the gateway files such an email)
        self.assertFalse(second.edi_pending_notices)
        notice = self._notice(second.record)
        self.assertEqual(self._mails(notice).email_to, SHOP_EMAIL)
        inbound = self.env["mail.message"].search(
            [("message_id", "=", second.inbound_message_id)]
        )
        self.assertEqual(len(inbound), 1)
        self.assertGreater(notice.id, inbound.id)

    # -- the flag is the system's -------------------------------------------------

    def test_users_cannot_flag_messages_as_outstanding_notices(self):
        order = self.env["purchase.order"].create({"partner_id": self.vendor.id})
        message = order.message_post(
            body="Mine", partner_ids=[self.manager.partner_id.id]
        )
        # the manager is a recipient of the message and may write to it, but
        # not to the field that decides whose notifications get cleared
        message = message.with_user(self.manager)
        with self.assertRaises(AccessError):
            message.write({"edi_notice_outstanding": True})
        self.assertFalse(message.sudo().edi_notice_outstanding)
