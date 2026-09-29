# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import models


class WizardBaseImportPdfUploadLine(models.TransientModel):
    _inherit = "wizard.base.import.pdf.upload.line"

    def _process_form(self):
        """Same contract as the base method - the only place
        `create_missing` is allowed to actually create anything (see
        `import_create_missing.CREATE_MISSING_ENABLED_KEY`). Covers both
        a manual upload (`action_process` calls this directly) and the
        EDI email intake path (`import_from_email`'s
        `EdiInputProcessTemplate` calls `line._process_form()` on the
        same model) - neither a preview wizard nor any onchange/compute
        goes through this method, so a template's live preview never
        creates a document.
        """
        return super(
            WizardBaseImportPdfUploadLine,
            self.with_context(import_create_missing=True),
        )._process_form()

    def _child_line_error_hint(self, template, values):
        """Extends `base_import_pdf_by_template_engine`'s child-line error
        message: when this template has at least one 'Create New Document
        if Not Found' line, a required field left empty is often that
        creation not running or failing rather than a plain extraction
        miss - point at where the real reason is already logged (see
        `base.import.pdf.template.line._log_create_missing()`) rather
        than leaving the reader to guess."""
        hint = super()._child_line_error_hint(template, values)
        if not template.line_ids.filtered("create_missing"):
            return hint
        return self.env._(
            "This template has 'Create New Document if Not Found' lines - "
            "if this value was supposed to come from one of those, check "
            "Settings > Technical > Logging (Path = import_create_missing) "
            "for why it didn't."
        )
