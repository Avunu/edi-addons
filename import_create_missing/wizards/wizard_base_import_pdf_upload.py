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
