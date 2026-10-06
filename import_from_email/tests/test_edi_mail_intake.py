# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from base64 import b64decode

from odoo.exceptions import UserError

from odoo.addons.base.tests.common import BaseCommon


class TestEdiMailIntake(BaseCommon):
    """`edi.exchange.record.message_new()` is what a `mail.alias` pointed at
    this model actually calls. `quick_exec` is left off on the exchange type
    here so record creation doesn't also try to run a processing component -
    that belongs to whatever module implements `input.process.<something>`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        backend_type = cls.env["edi.backend.type"].create(
            {"name": "Test EDI Backend Type", "code": "test_edi_backend_type"}
        )
        cls.backend = cls.env["edi.backend"].create(
            {"name": "Test EDI Backend", "backend_type_id": backend_type.id}
        )
        cls.exchange_type = cls.env["edi.exchange.type"].create(
            {
                "name": "Parts Supplier PO Confirmation",
                "code": "parts_supplier_po_confirmation",
                "direction": "input",
                "backend_type_id": backend_type.id,
                "backend_id": cls.backend.id,
                "quick_exec": False,
            }
        )

    def _custom_values(self, **extra):
        return {
            "backend_id": self.backend.id,
            "type_code": self.exchange_type.code,
            **extra,
        }

    def test_message_new_creates_exchange_record(self):
        msg_dict = {
            "body": "<p>Order #: ORD-00000TESTA</p>",
            "message_id": "<abc123@parts-supplier.example>",
        }
        record = self.env["edi.exchange.record"].message_new(
            msg_dict, self._custom_values()
        )
        self.assertEqual(record.type_id, self.exchange_type)
        self.assertEqual(record.backend_id, self.backend)
        self.assertEqual(record.exchange_filename, "<abc123@parts-supplier.example>.html")
        # the whole document is already in hand - no separate "receive"
        # round-trip needed, so `quick_exec` must see it as ready to process
        self.assertEqual(record.edi_exchange_state, "input_received")
        self.assertIn(
            "ORD-00000TESTA", b64decode(record.exchange_file).decode()
        )

    def test_message_new_without_backend_id_raises(self):
        with self.assertRaises(UserError):
            self.env["edi.exchange.record"].message_new(
                {"body": "<p>hi</p>"}, {"type_code": self.exchange_type.code}
            )

    def test_message_new_without_type_code_raises(self):
        # `type_id` is required on this model and has no sensible default,
        # so a misconfigured alias (missing a default) must fail loudly
        # rather than error out obscurely on a missing required field.
        with self.assertRaises(UserError):
            self.env["edi.exchange.record"].message_new(
                {"body": "<p>hi</p>"}, {"backend_id": self.backend.id}
            )

    def test_message_new_unknown_backend_raises(self):
        bogus_id = self.backend.id + 10000
        self.assertFalse(self.env["edi.backend"].browse(bogus_id).exists())
        with self.assertRaises(UserError):
            self.env["edi.exchange.record"].message_new(
                {"body": "<p>hi</p>"},
                self._custom_values(backend_id=bogus_id),
            )

    def test_message_new_unknown_type_code_raises(self):
        # No matching `edi.exchange.type` for this backend: the framework's
        # own `create_record()` enforces this via a plain `assert`.
        with self.assertRaises(AssertionError):
            self.env["edi.exchange.record"].message_new(
                {"body": "<p>hi</p>"},
                self._custom_values(type_code="does_not_exist"),
            )

    def test_message_update_creates_a_new_exchange_record(self):
        # Odoo's mail gateway calls message_update() (not message_new())
        # whenever an inbound message's References/In-Reply-To headers match
        # a Message-Id it already has on file - which happens whenever a
        # mail client keeps two unrelated forwarded documents under the same
        # subject/conversation. Each inbound EDI email must still become its
        # own independent exchange record rather than being silently folded
        # into the record message_update() was called on.
        first = self.env["edi.exchange.record"].message_new(
            {"body": "<p>first PO</p>", "message_id": "<first@example.com>"},
            self._custom_values(),
        )
        second = first.message_update(
            {"body": "<p>second PO</p>", "message_id": "<second@example.com>"},
            self._custom_values(),
        )
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(second.type_id, self.exchange_type)
        self.assertEqual(second.edi_exchange_state, "input_received")
        self.assertIn("second PO", b64decode(second.exchange_file).decode())
