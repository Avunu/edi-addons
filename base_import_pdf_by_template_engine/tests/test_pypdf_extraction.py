# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from io import BytesIO

import pypdf

from odoo.addons.base.tests.common import BaseCommon


class TestPypdfExtraction(BaseCommon):
    def test_small_pdf_is_read_back_from_disk(self):
        """A PDF smaller than Python's write buffer must still reach pypdf:
        `simple_pdf_text_extraction()` writes it to a temp file and never
        flushes, so without the flush in `_pdf_text_extraction_pypdf()`
        pypdf reads an empty file and the extraction fails."""
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buffer = BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()
        self.assertLess(len(data), 8192)
        # An abstract model has no `id`, so `.new()` on the bare mixin
        # fails; use a concrete model that inherits it.
        wizard = self.env["wizard.base.import.pdf.preview"].new(
            {"extraction_mode": "pypdf"}
        )
        self.assertEqual(len(wizard.simple_pdf_text_extraction(data)), 1)
