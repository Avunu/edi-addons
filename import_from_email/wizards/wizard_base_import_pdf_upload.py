# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models


class WizardBaseImportPdfUploadLine(models.TransientModel):
    _inherit = "wizard.base.import.pdf.upload.line"

    pinned_template_id = fields.Many2one(
        "base.import.pdf.template",
        help="A template to use as-is, bypassing auto-detection entirely - "
        "set by a caller (edi_input_process_template.py) that already "
        "knows the exact template to use and never sets attachment_id, so "
        "there is nothing for the base compute to auto-detect against.",
    )

    @api.depends("attachment_id", "pinned_template_id")
    def _compute_template_id(self):
        """Fall back to `pinned_template_id` for a line with no
        `attachment_id`.

        The base compute unconditionally blanks `template_id` first, then
        only re-derives it (via auto-detection against the attachment's
        own text) for lines that *have* an `attachment_id` - see its own
        `self.filtered("attachment_id")`. `edi_input_process_template.py`
        never sets `attachment_id` at all: it already knows the exact
        template from the exchange type (`exchange_record.type_id.
        import_template_id`), so there is nothing to auto-detect.

        This can't just capture `self.template_id` and restore it after
        calling `super()`, tempting as that looks - `_compute_template_id`
        only runs when `template_id`'s own cache has *already* been
        invalidated, so reading `self.template_id` from inside this
        method (even before calling `super()`) reads that same emptied
        cache, not whatever it held a moment ago. `pinned_template_id` is
        a plain, uncomputed field instead, immune to that invalidation,
        so it survives exactly the same `odoo.tests.Form` onchange
        machinery that wipes `template_id` deep inside processing this
        line's own child table. Traced to exactly this after a live
        import kept failing with `"'product_id' is a required field"` on
        data that itself extracted and resolved correctly - see
        product_napaonline_lookup's README for the fuller story of that
        investigation.
        """
        super()._compute_template_id()
        for rec in self:
            if not rec.attachment_id and rec.pinned_template_id:
                rec.template_id = rec.pinned_template_id
