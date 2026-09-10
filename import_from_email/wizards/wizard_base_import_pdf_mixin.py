# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import base64
import logging
import re

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

logger = logging.getLogger(__name__)


class WizardBaseImportPdfMixin(models.AbstractModel):
    _inherit = "wizard.base.import.pdf.mixin"

    def _read_text_file(self, fileobj):
        """Read back the temp file `simple_pdf_text_extraction()` wrote to disk.

        The file holds whatever bytes were on the source attachment (a plain
        text or HTML body, not a PDF), so it is read back as text rather than
        handed to a PDF parser.

        `simple_pdf_text_extraction()` writes to `fileobj` but never flushes
        it before calling us - Python's buffered writer holds small writes
        (anything under its ~8KB default buffer) in memory, so opening the
        same path through a second file handle can read back 0 bytes. Real
        PDFs are usually big enough to overflow that buffer on their own,
        masking the issue for `pypdf`; a short plaintext/HTML email body
        reliably is not. Flush first so the bytes are actually on disk.
        """
        fileobj.flush()
        with open(fileobj.name, encoding="utf-8", errors="replace") as f:
            return f.read()

    def _pdf_text_extraction_plaintext(self, fileobj):
        res = False
        try:
            text = self._read_text_file(fileobj)
            res = [text] if text else False
            logger.info("Text extraction made with plaintext")
        except Exception as e:
            logger.warning("Text extraction with plaintext failed. Error: %s", e)
        return res

    def _pdf_text_extraction_html(self, fileobj):
        res = False
        try:
            html_source = self._read_text_file(fileobj)
            text = html2plaintext(self._div_breaks(html_source))
            res = [text] if text else False
            logger.info("Text extraction made with html2plaintext")
        except Exception as e:
            logger.warning("Text extraction with html failed. Error: %s", e)
        return res

    def _div_breaks(self, html_source):
        """Inject a newline before every `<div>` opening tag.

        `odoo.tools.html2plaintext()` only turns `<tr>`, `</p>`, and `<br>`
        into line breaks - it has no handling for `<div>` at all. An email
        body built entirely out of `<div>` blocks (one per logical line,
        as several NAPA order confirmations are) then collapses into one
        single continuous line with no newlines whatsoever once tags are
        stripped, which silently breaks every `base.import.pdf.template.
        line` pattern anchored with `^`/`$` (they need MULTILINE line
        boundaries to match anything) and - worse - desyncs
        `_get_table_info_data()`'s purely positional column-to-row zip:
        a pattern that matches zero times for one column doesn't remove a
        row, it shifts every later column's value one slot to the left for
        every row, silently. This was traced against a real captured NAPA
        order confirmation (see product_napaonline_lookup's README) before
        fixing it here.
        """
        return re.sub(r"(?i)<div", "\n<div", html_source)

    def _parse_pdf_grouped(self):
        """Like the base implementation, but a mode that cannot parse the
        attachment yields an empty result instead of aborting the whole
        grouped parse.

        The base loop feeds every registered extraction mode through
        `simple_pdf_text_extraction()`, which raises `UserError` when a
        mode comes back empty - reasonable when `pypdf` is the only mode
        (a non-PDF attachment is an error worth reporting), but fatal
        once this module registers `plaintext`/`html`: auto-detection
        (`wizard.base.import.pdf.upload`, before any template - and so
        any extraction mode - is known) groups across *all* modes, and a
        text/HTML email body reliably defeats `pypdf`. Without the
        tolerance here, the first mode to fail would abort the loop and
        the modes that could have parsed the attachment would never run
        (see test_grouped_parsing_tries_every_mode).
        """
        res = {}
        extraction_modes = dict(
            self._fields["extraction_mode"]._description_selection(self.env)
        )
        file_data = base64.b64decode(self.attachment_id.datas)
        for extraction_mode in list(extraction_modes.keys()):
            self.extraction_mode = extraction_mode
            try:
                res[extraction_mode] = self._fallback_parse_pdf(file_data)
            except UserError:
                res[extraction_mode] = False
        return res
