# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from base64 import b64encode

from odoo.exceptions import UserError

from odoo.addons.base.tests.common import BaseCommon


class TestGenericProcessor(BaseCommon):
    """`edi.input.process.template` is deliberately not about NAPA or
    purchase orders: this test drives it against `res.partner` to prove the
    same processor works for any document/model pair, as long as an exchange
    type points `import_template_id` at a matching `base.import.pdf.template`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        name_field = cls.env["ir.model.fields"]._get("res.partner", "name")
        res_partner_model = cls.env["ir.model"]._get("res.partner")
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Test Partner Template",
                "extraction_mode": "plaintext",
                "model_id": res_partner_model.id,
                "auto_detect_pattern": "Partner Name:",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "related_model": "header",
                            "field_id": name_field.id,
                            "pattern": r"Partner Name: (.+)",
                        },
                    )
                ],
            }
        )
        backend_type = cls.env["edi.backend.type"].create(
            {"name": "Test Generic Backend Type", "code": "test_generic_backend_type"}
        )
        cls.backend = cls.env["edi.backend"].create(
            {"name": "Test Generic Backend", "backend_type_id": backend_type.id}
        )
        processor_model = cls.env["ir.model"]._get("edi.input.process.template")
        cls.exchange_type = cls.env["edi.exchange.type"].create(
            {
                "name": "Generic Template Import",
                "code": "generic_template_import",
                "direction": "input",
                "backend_type_id": backend_type.id,
                "backend_id": cls.backend.id,
                "process_model_id": processor_model.id,
                "import_template_id": cls.template.id,
                "quick_exec": True,
            }
        )

    def _create_exchange_record(self, body):
        return self.env["edi.exchange.record"].create(
            {
                "backend_id": self.backend.id,
                "type_id": self.exchange_type.id,
                "exchange_file": b64encode(body.encode()),
                "edi_exchange_state": "input_received",
            }
        )

    def test_quick_exec_creates_partner_from_plaintext(self):
        # quick_exec runs the processor synchronously as part of create()
        exchange_record = self._create_exchange_record("Partner Name: Acme Corp")
        self.assertEqual(exchange_record.edi_exchange_state, "input_processed")
        self.assertEqual(exchange_record.record._name, "res.partner")
        self.assertEqual(exchange_record.record.name, "Acme Corp")

    def test_process_without_import_template_raises(self):
        self.exchange_type.import_template_id = False
        exchange_record = self._create_exchange_record("Partner Name: Acme Corp")
        # the error is caught by exchange_process() and stored on the
        # record rather than propagated, per edi_backend.exchange_process()
        self.assertEqual(exchange_record.edi_exchange_state, "input_processed_error")
        self.assertIn("Import Template", exchange_record.exchange_error)

    def test_process_raises_directly_without_import_template(self):
        # Calling the processor directly (rather than going through
        # `exchange_process()`, which is what quick_exec already exercised
        # in the previous test) surfaces the real UserError instead of it
        # being swallowed into `exchange_error`.
        self.exchange_type.import_template_id = False
        exchange_record = self._create_exchange_record("Partner Name: Acme Corp")
        with self.assertRaises(UserError):
            self.env["edi.input.process.template"].process(exchange_record)
