# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import models


class WizardBaseImportPdfMixin(models.AbstractModel):
    _inherit = "wizard.base.import.pdf.mixin"

    def _pdf_text_extraction_pypdf(self, fileobj):
        """Same contract as the base method, but flushes `fileobj` first.

        `simple_pdf_text_extraction()` writes the attachment to `fileobj`
        and never flushes it before calling the extraction method, and
        `pypdf` then opens the same path through a second file handle.
        Python's buffered writer holds anything under its ~8KB default
        buffer in memory, so a small PDF reads back as an empty file
        ("Cannot read an empty file") and the extraction fails. A larger
        PDF only works because it overflows the buffer on its own - and
        even then only up to the last full buffer. See the same fix for
        text and HTML in `import_from_email` and for xberg in
        `import_via_xberg`.
        """
        fileobj.flush()
        return super()._pdf_text_extraction_pypdf(fileobj)
