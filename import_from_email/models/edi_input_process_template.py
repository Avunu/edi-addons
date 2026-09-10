# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

from odoo import models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class EdiInputProcessTemplate(models.AbstractModel):
    """Generic EDI input processor: extract + create via an import template.

    This is deliberately model-agnostic - it doesn't know about purchase
    orders, NAPA, or any other specific document. Any `edi.exchange.type`
    that sets this as its Processor and points `import_template_id` at a
    `base.import.pdf.template` gets a working input flow: whatever model
    and fields that template targets is what gets created, driven by the
    same `Form()`-based engine `base_import_pdf_by_template` already uses
    for a manually uploaded file. Add another exchange type + template pair
    for each new document/sender combination - no new code required.

    A document that needs more than the template engine's exact-match field
    mapping (fuzzy partner/product matching, safe updates to an existing
    record, dedup, ...) should get its own dedicated processor instead of
    this one, reusing whichever `*_import` wizard fits (e.g.
    `purchase_order_import`) - this generic path stays the default for
    everything simpler than that.
    """

    _name = "edi.input.process.template"
    _inherit = "edi.oca.handler.process"
    _description = "EDI Input Process: Import by Template"

    def process(self, exchange_record):
        template = exchange_record.type_id.import_template_id
        if not template:
            raise UserError(
                self.env._(
                    "Exchange type '%s' has no Import Template configured.",
                    exchange_record.type_id.display_name,
                )
            )
        raw = exchange_record._get_file_content(binary=True, as_bytes=True)
        # A persisted record (create()), not an in-memory one (new()):
        # deep inside `line._process_form()`, `odoo.tests.Form` builds a
        # *nested* Form for this line's own child table
        # (`base_import_pdf_by_template`'s own `_process_child_lines()`),
        # and that nested Form's onchange machinery makes every field on
        # an in-memory `.new()` record - not just computed ones - read
        # back empty for the rest of this call. A real row doesn't have
        # that problem; its fields come from the database on every
        # access, not from an in-memory cache that machinery invalidates.
        # This wizard is a TransientModel - Odoo's own periodic vacuum
        # cleans up the row, the same as any other wizard's.
        #
        # pinned_template_id, not template_id directly: template_id is a
        # computed field that only re-derives itself from `attachment_id`
        # (which this flow never sets, it already knows the exact
        # template), so it would otherwise just get computed back to
        # False regardless of which kind of record this is - see
        # wizards/wizard_base_import_pdf_upload.py's
        # _compute_template_id() override for the full story.
        line = self.env["wizard.base.import.pdf.upload.line"].create({})
        line.pinned_template_id = template.id
        pages = line.simple_pdf_text_extraction(raw)
        line.data = "".join(pages)
        record = line._process_form()
        exchange_record._set_related_record(record)
        logger.info(
            "Exchange %s created %s %s via template '%s'",
            exchange_record.identifier,
            record._name,
            record.id,
            template.name,
        )
        return self.env._(
            "%(model)s '%(name)s' created",
            model=record._name,
            name=record.display_name,
        )
