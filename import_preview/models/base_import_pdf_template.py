# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models

PREVIEW_SUMMARY_MAX_ROWS = 25


class BaseImportPdfTemplate(models.Model):
    _inherit = "base.import.pdf.template"

    sample_data = fields.Text(
        string="Sample data",
        help="A persistent reference document for this template: plain "
        "text for most extraction modes, or the JSON envelope for a mode "
        "like Xberg. Paste it directly, or upload a file below and it will "
        "be filled in automatically using this template's own extraction "
        "mode. Every line's pattern is matched against this text live "
        "while you edit it.",
    )
    sample_file = fields.Binary(string="Load sample from file", attachment=True)
    sample_filename = fields.Char()
    preview_summary = fields.Text(
        string="Preview", compute="_compute_preview_summary", store=False
    )

    def _preview_summary_depends(self):
        """Extension point mirroring `line._preview_depends()` - a module
        changing what a line extracts appends the relevant `line_ids.*`
        path here."""
        return [
            "sample_data",
            "line_ids.pattern",
            "line_ids.related_model",
            "line_ids.field_id",
            "line_ids.value_type",
        ]

    @api.depends(lambda self: self._preview_summary_depends())
    def _compute_preview_summary(self):
        for template in self:
            if not template.sample_data:
                template.preview_summary = False
                continue
            try:
                template.preview_summary = template._render_preview_summary()
            except Exception as err:  # pylint: disable=W8138
                template.preview_summary = self.env._(
                    "⚠ %(error_type)s: %(error)s",
                    error_type=type(err).__name__,
                    error=err,
                )

    def _render_preview_summary(self):
        self.ensure_one()
        text = self.sample_data
        header_values = self._get_field_header_values(text)
        table_info = self._get_table_info(text)
        lines_values = self._get_field_child_values(table_info)
        parts = [self.env._("Header:")]
        if header_values:
            for field_name, value in header_values.items():
                parts.append(f"  {field_name}: {value!r}")
        else:
            parts.append(self.env._("  (no header values matched)"))
        parts.append("")
        parts.append(self.env._("Lines (%s):", len(lines_values)))
        for index, line_values in enumerate(
            lines_values[:PREVIEW_SUMMARY_MAX_ROWS], start=1
        ):
            parts.append(f"  {index:>3}. {line_values!r}")
        if len(lines_values) > PREVIEW_SUMMARY_MAX_ROWS:
            parts.append(
                self.env._(
                    "  … and %s more", len(lines_values) - PREVIEW_SUMMARY_MAX_ROWS
                )
            )
        return "\n".join(parts)

    @api.onchange("sample_file")
    def _onchange_sample_file(self):
        """Run the template's own extraction pipeline against the uploaded
        file, the same way a real import would, so `sample_data` never has
        to be hand-typed for a binary source format like a PDF or the
        Xberg JSON envelope. Reuses `wizard.base.import.pdf.preview`'s
        `_parse_pdf()` rather than duplicating extraction-mode dispatch.
        """
        for template in self.filtered("sample_file"):
            try:
                wizard = self.env["wizard.base.import.pdf.preview"].new(
                    {"extraction_mode": template.extraction_mode}
                )
                template.sample_data = "".join(
                    wizard._parse_pdf(template.sample_file)
                )
            except Exception as err:  # pylint: disable=W8138
                # A bad upload must never block saving the template - it
                # just means `sample_data` doesn't get filled in.
                return {
                    "warning": {
                        "title": self.env._("Could not extract sample data"),
                        "message": str(err),
                    }
                }
