# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from base64 import b64encode
from os import path

from odoo.addons.base.tests.common import BaseCommon


class TestExtractionModes(BaseCommon):
    """`plaintext` and `html` mirror a real NAPA Prolink order confirmation
    email (tests/data/napa_order_confirmation.*) so a regex template built
    against these fixtures is known to match the real thing.
    """

    def _data_file(self, filename):
        filename = "data/" + filename
        with open(path.join(path.dirname(__file__), filename), "rb") as file:
            return file.read()

    def _mixin(self, extraction_mode):
        # wizard.base.import.pdf.mixin is an AbstractModel - .new() on it
        # directly raises (`'...mixin' object has no attribute 'id'`, Odoo
        # 18's NewId machinery expects a real model). Any TransientModel
        # that inherits the mixin works fine; wizard.base.import.pdf.upload.
        # line is the lightest one available.
        return self.env["wizard.base.import.pdf.upload.line"].new(
            {"extraction_mode": extraction_mode}
        )

    def test_extraction_mode_selection_extended(self):
        selection = dict(
            self.env["base.import.pdf.template"]
            ._fields["extraction_mode"]
            ._description_selection(self.env)
        )
        self.assertIn("plaintext", selection)
        self.assertIn("html", selection)
        # the original mode from base_import_pdf_by_template must still work
        self.assertIn("pypdf", selection)

    def test_plaintext_extraction(self):
        data = self._data_file("napa_order_confirmation.txt")
        res = self._mixin("plaintext").simple_pdf_text_extraction(data)
        self.assertEqual(res, [data.decode("utf-8")])
        text = res[0]
        self.assertIn("Order #: NPPLK-00000TESTA", text)
        self.assertIn("Cost $114.96 /Each", text)
        self.assertIn("Qty/Car 1", text)

    def test_html_extraction(self):
        data = self._data_file("napa_order_confirmation.html")
        res = self._mixin("html").simple_pdf_text_extraction(data)
        self.assertTrue(res)
        text = res[0]
        self.assertIn("NPPLK-00000TESTA", text)
        self.assertIn("265.75", text)
        self.assertIn("114.96", text)
        self.assertIn("Qty/Car", text)

    def test_div_breaks_injects_a_newline_before_each_div(self):
        mixin = self._mixin("html")
        self.assertEqual(
            mixin._div_breaks("<div>a</div><div>b</div>"),
            "\n<div>a</div>\n<div>b</div>",
        )

    def test_html_extraction_preserves_div_boundaries_as_lines(self):
        """A real NAPA order confirmation (napa_order_confirmation_div.html,
        captured from a live production import) is built entirely out of
        `<div>` blocks, not `<table>`/`<tr>` like the fixture above -
        `html2plaintext()` has no handling for `<div>` at all, so without
        `_div_breaks()` every block collapses onto one continuous line.
        That silently breaks two things downstream: a `^`/`$`-anchored
        template pattern (the shape product_napaonline_lookup's own
        template uses for its part-number column) can never match
        anything, and `base.import.pdf.template._get_table_info_data()`'s
        purely positional column-to-row zip desyncs - a column with zero
        matches doesn't remove a row, it shifts every later column's value
        into the wrong row instead, for every row. This is exactly what
        happened in production before `_div_breaks()` was added: every
        line item's `product_id` search value came out as the quantity
        ("1") instead of the real part number.
        """
        data = self._data_file("napa_order_confirmation_div.html")
        res = self._mixin("html").simple_pdf_text_extraction(data)
        lines = res[0].splitlines()
        # each part number is its own line - not glued to the vendor name
        # immediately following it in the source, nor to anything else
        self.assertIn("NCP 2605438", lines)
        self.assertIn("ECH EC235", lines)
        self.assertIn("FPG VS50546R", lines)
        self.assertIn("NAPA", lines)

    def test_grouped_parsing_tries_every_mode(self):
        """`_parse_pdf_grouped()` (used for template auto-detection before a
        template, and therefore an extraction mode, is known) must keep
        working once new modes are registered: `pypdf` fails silently on a
        non-PDF attachment while `plaintext` succeeds.
        """
        data = self._data_file("napa_order_confirmation.txt")
        attachment = self.env["ir.attachment"].create(
            {
                "name": "napa_order_confirmation.txt",
                "datas": b64encode(data),
            }
        )
        line = self.env["wizard.base.import.pdf.upload.line"].new(
            {"attachment_id": attachment.id}
        )
        grouped = line._parse_pdf_grouped()
        self.assertFalse(grouped["pypdf"])
        self.assertIn("NPPLK-00000TESTA", "".join(grouped["plaintext"]))
