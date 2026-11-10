# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo.tests import tagged

from odoo.addons.base.tests.common import BaseCommon
from odoo.addons.import_from_email.models.edi_exchange_record import (
    MAX_REPLY_ADDRESSES,
)

ALIAS_DOMAIN = "reply-test.example"
ALIAS_EMAIL = f"orders-in@{ALIAS_DOMAIN}"

GMAIL_FORWARD = """\
Delivered-To: {alias}
Received: by 2002:a05:6a10:1 with SMTP id c1csp1;
        Mon, 9 Nov 2026 02:00:00 -0800 (PST)
X-Forwarded-For: shop@shop.example {alias}
X-Forwarded-To: {alias}
Delivered-To: shop@shop.example
Message-Id: <{n}@vendor.example>
{threading}Subject: Order confirmation {n}
From: Vendor Sales <sales@vendor.example>
To: {to}
Cc: copied@elsewhere.example
Date: Mon, 09 Nov 2026 10:00:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

Order #: {n}
"""

MANUAL_FORWARD = """\
Delivered-To: {alias}
Message-Id: <{n}@shop.example>
{threading}Subject: Fwd: Order confirmation {n}
From: Shop Person <person@shop.example>
To: {alias}
Date: Mon, 09 Nov 2026 10:00:00 +0000
MIME-Version: 1.0
Content-Type: text/plain; charset="utf-8"

---------- Forwarded message ---------
Order #: {n}
"""


@tagged("post_install", "-at_install")
class TestReplyAddresses(BaseCommon):
    """Where a reply to an inbound email should go: the shop-side mailbox that
    received the vendor's email and forwarded it to the Odoo alias."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        backend_type = cls.env["edi.backend.type"].create(
            {"name": "Reply test type", "code": "reply_test_backend_type"}
        )
        cls.backend = cls.env["edi.backend"].create(
            {"name": "Reply test backend", "backend_type_id": backend_type.id}
        )
        cls.exchange_type = cls.env["edi.exchange.type"].create(
            {
                "name": "Reply test",
                "code": "reply_test",
                "direction": "input",
                "backend_type_id": backend_type.id,
                "backend_id": cls.backend.id,
                "quick_exec": False,
            }
        )
        domain = cls.env["mail.alias.domain"].create({"name": ALIAS_DOMAIN})
        cls.alias = cls.env["mail.alias"].create(
            {
                "alias_name": "orders-in",
                "alias_domain_id": domain.id,
                "alias_model_id": cls.env["ir.model"]._get("edi.exchange.record").id,
                "alias_contact": "everyone",
                "alias_defaults": repr(
                    {"backend_id": cls.backend.id, "type_code": "reply_test"}
                ),
            }
        )
        cls.domain = domain

    def _receive(
        self,
        raw,
        n,
        to="shop@shop.example, other@shop.example",
        threading="",
    ):
        before = self.env["edi.exchange.record"].search([]).ids
        self.env["mail.thread"].message_process(
            None, raw.format(alias=ALIAS_EMAIL, n=n, to=to, threading=threading)
        )
        record = self.env["edi.exchange.record"].search([("id", "not in", before)])
        self.assertEqual(len(record), 1)
        return record

    def _addresses(self, msg_dict, **headers):
        return self.env["edi.exchange.record"]._inbound_reply_addresses(
            msg_dict, headers or None
        )

    def test_gmail_forwarding_rule(self):
        # From the vendor, To the shop mailbox (plus a colleague), forwarded
        # by a Gmail rule: the mailbox that forwarded it is X-Forwarded-For.
        # Its own Delivered-To (below the Odoo side's one) is no obstacle; Cc
        # is not a recipient of replies, the vendor and the alias never are.
        record = self._receive(GMAIL_FORWARD, 1)
        self.assertEqual(record.inbound_reply_to, "shop@shop.example")

    def test_without_x_forwarded_for_the_original_to_is_used(self):
        raw = GMAIL_FORWARD.replace("X-Forwarded-For: shop@shop.example {alias}\n", "")
        record = self._receive(raw, 11)
        self.assertEqual(
            record.inbound_reply_to, "shop@shop.example, other@shop.example"
        )

    def test_colleagues_of_the_sender_are_not_in_the_original_to(self):
        raw = GMAIL_FORWARD.replace("X-Forwarded-For: shop@shop.example {alias}\n", "")
        record = self._receive(
            raw, 12, to="shop@shop.example, accounting@vendor.example"
        )
        self.assertEqual(record.inbound_reply_to, "shop@shop.example")
        # ... unless the sender's domain is a mailbox provider anybody has
        self.assertEqual(
            self._addresses(
                {"email_from": "someone@gmail.com"},
                to=["shop@shop.example", "other@gmail.com"],
            ),
            ["shop@shop.example", "other@gmail.com"],
        )

    def test_at_most_a_handful_of_addresses(self):
        many = [f"user{i}@shop.example" for i in range(30)]
        self.assertEqual(
            len(self._addresses({"email_from": "sales@vendor.example"}, to=many)),
            MAX_REPLY_ADDRESSES,
        )
        self.assertEqual(
            len(
                self._addresses(
                    {"email_from": "sales@vendor.example"}, x_forwarded_for=many
                )
            ),
            MAX_REPLY_ADDRESSES,
        )

    def test_an_email_colliding_with_an_earlier_exchange_keeps_the_headers(self):
        # The gateway calls message_update() (without any update_vals) when
        # the References match an earlier exchange: the new exchange is filed
        # under the same backend/type, with the same routing headers read.
        first = self._receive(GMAIL_FORWARD, 13)
        record = self._receive(
            GMAIL_FORWARD,
            14,
            threading="In-Reply-To: <13@vendor.example>\n"
            "References: <13@vendor.example>\n",
        )
        self.assertNotEqual(first, record)
        self.assertEqual(record.type_id, first.type_id)
        self.assertEqual(record.inbound_reply_to, "shop@shop.example")

    def test_manual_forward_falls_back_to_the_forwarder(self):
        record = self._receive(MANUAL_FORWARD, 2)
        self.assertEqual(record.inbound_reply_to, "person@shop.example")

    def test_instance_addresses_are_never_reply_addresses(self):
        instance = {
            self.alias.alias_full_name,
            self.domain.catchall_email,
            self.domain.bounce_email,
            self.domain.default_from_email,
        }
        self.assertEqual(len(instance), 4)
        for address in instance:
            self.assertIn(
                address, self.env["edi.exchange.record"]._inbound_instance_addresses()
            )
            self.assertEqual(
                self._addresses(
                    {"email_from": "sales@vendor.example"},
                    to=[address, "shop@shop.example"],
                ),
                ["shop@shop.example"],
            )
            # forwarder fallback skips them too
            self.assertEqual(
                self._addresses({"email_from": address}, to=[ALIAS_EMAIL]), []
            )

    def test_x_forwarded_for_names_the_forwarder(self):
        # the original To was a list/alias at the shop; the mailbox that
        # actually forwarded is named by X-Forwarded-For, and answers
        self.assertEqual(
            self._addresses(
                {"email_from": "sales@vendor.example"},
                to=["team@shop.example"],
                x_forwarded_for=["Shop@shop.example", ALIAS_EMAIL],
                x_forwarded_to=[ALIAS_EMAIL],
                delivered_to=[ALIAS_EMAIL],
            ),
            ["shop@shop.example"],
        )

    def test_delivery_headers_are_not_reply_addresses(self):
        self.assertEqual(
            self._addresses(
                {"email_from": "sales@vendor.example"},
                to=["shop@shop.example", "relay@mx.example"],
                delivered_to=["relay@mx.example"],
            ),
            ["shop@shop.example"],
        )
        # only the top-most Delivered-To/X-Original-To is the Odoo side's: the
        # ones below were added by the shop's own mail server
        self.assertEqual(
            self._addresses(
                {"email_from": "sales@vendor.example"},
                to=["shop@shop.example", "relay@mx.example"],
                delivered_to=["relay@mx.example", "shop@shop.example"],
            ),
            ["shop@shop.example"],
        )
        # X-Original-To is whatever the shop's mail server made of it
        self.assertEqual(
            self._addresses(
                {"email_from": "sales@vendor.example"},
                to=["shop@shop.example"],
                x_original_to=["shop@shop.example"],
            ),
            ["shop@shop.example"],
        )
        self.assertEqual(
            self._addresses(
                {"email_from": "sales@vendor.example"},
                to=["shop@shop.example", "relay@mx.example"],
                x_forwarded_to=["relay@mx.example"],
            ),
            ["shop@shop.example"],
        )

    def test_the_original_sender_is_left_out(self):
        self.assertEqual(
            self._addresses(
                {"email_from": '"Vendor" <Sales@Vendor.example>'},
                to=["sales@vendor.example", "shop@shop.example"],
            ),
            ["shop@shop.example"],
        )

    def test_no_reply_addresses_are_left_out(self):
        for local in (
            "noreply",
            "no-reply",
            "no_reply",
            "donotreply",
            "do-not-reply",
            "mailer-daemon",
            "postmaster",
            "bounce",
            "noreply+x",
        ):
            address = f"{local}@shop.example"
            self.assertEqual(
                self._addresses(
                    {"email_from": "sales@vendor.example"},
                    to=[address, "shop@shop.example"],
                ),
                ["shop@shop.example"],
                address,
            )
            self.assertEqual(
                self._addresses({"email_from": address}, to=[ALIAS_EMAIL]), [], address
            )

    def test_nothing_determinable(self):
        self.assertEqual(self._addresses({}), [])
        self.assertEqual(self._addresses({"email_from": "", "to": ""}), [])

    def test_without_headers_only_the_flattened_to_is_known(self):
        # message_new() called directly (no route custom values)
        self.assertEqual(
            self.env["edi.exchange.record"]._inbound_reply_addresses(
                {
                    "email_from": "sales@vendor.example",
                    "to": f"shop@shop.example,{ALIAS_EMAIL}",
                }
            ),
            ["shop@shop.example"],
        )

    def test_message_new_stores_the_reply_addresses(self):
        record = self.env["edi.exchange.record"].message_new(
            {
                "body": "<p>x</p>",
                "message_id": "<direct@vendor.example>",
                "email_from": "sales@vendor.example",
                "to": "shop@shop.example",
            },
            {"backend_id": self.backend.id, "type_code": "reply_test"},
        )
        self.assertEqual(record.inbound_reply_to, "shop@shop.example")
        record = self.env["edi.exchange.record"].message_new(
            {"body": "<p>x</p>", "message_id": "<direct2@vendor.example>"},
            {"backend_id": self.backend.id, "type_code": "reply_test"},
        )
        self.assertFalse(record.inbound_reply_to)
