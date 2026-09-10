# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models

PREVIEW_MAX_CHARS = 4000
PREVIEW_MAX_ROWS = 25

#: Every field that changes what a line extracts. Listing them here does
#: double duty: `@api.depends` recomputes `preview_result` when any of them
#: changes, AND `ir.ui.view._postprocess_on_change` only marks a field's
#: view node `on_change="1"` when some field *in the same view* depends on
#: it - which is what makes the preview update live as the user edits the
#: line dialog, not just after they save it.
PREVIEW_DEPENDS = (
    "pattern",
    "related_model",
    "field_id",
    "value_type",
    "date_format",
    "time_format",
    "decimal_separator",
    "thousand_separator",
    "search_field_id",
    "search_subfield_id",
    "default_value",
    "mapped_ids",
    "mapped_ids.origin",
    "mapped_ids.value",
    "template_id.sample_data",
)


class BaseImportPdfTemplateLine(models.Model):
    _inherit = "base.import.pdf.template.line"

    # A non-stored mirror of the template's sample, shown next to the
    # preview so a stale match (see the "known minor gap" in the README) is
    # visible and self-correcting rather than silently wrong.
    sample_data = fields.Text(related="template_id.sample_data", readonly=True)
    preview_result = fields.Text(
        string="Preview", compute="_compute_preview_result", store=False
    )

    def _preview_depends(self):
        """Extension point: a module adding a field that changes what a
        line extracts (e.g. `import_via_xberg`'s `xberg_jsonpath`) appends
        its name here by overriding this method - `@api.depends` on a
        compute override merges with the base's across the whole MRO, and
        `depends` accepts a callable evaluated once at registry setup."""
        return list(PREVIEW_DEPENDS)

    @api.depends(lambda self: self._preview_depends())
    def _compute_preview_result(self):
        for line in self:
            try:
                line.preview_result = line._render_preview()
            except Exception as err:  # pylint: disable=W8138
                # This compute runs on every web_read and every onchange -
                # it must never be able to break the form. The user is
                # actively authoring a pattern, so it being invalid
                # mid-keystroke (bad regex, bad JSONPath, bad JSON, a
                # strptime()/float() that doesn't parse, a search() the
                # user lacks access to) is the *expected* case, not a bug.
                line.preview_result = self.env._(
                    "⚠ %(error_type)s: %(error)s",
                    error_type=type(err).__name__,
                    error=err,
                )

    def _render_preview(self):
        self.ensure_one()
        sample = self.template_id.sample_data
        if not sample:
            return self.env._(
                "Paste or upload a sample document on the template's Sample "
                "Data tab to see what this line matches."
            )
        if not self.field_id:
            return False
        if self.value_type == "fixed":
            return repr(self._get_fixed_value())
        if not self.pattern:
            return self.env._("No pattern set.")
        if self.related_model == "lines":
            return self._render_preview_column(sample)
        return self._render_preview_header(sample)

    def _render_preview_header(self, sample):
        value = self._get_field_value(sample)
        if not value:
            return self.env._("No match.")
        if self.search_field_id and not isinstance(value, models.Model):
            # `_process_value()` falls back to the raw matched string when
            # the lookup finds nothing - the single most common template
            # mistake, otherwise invisible until the real import runs.
            return self.env._(
                "No %(model)s found with %(field)s = %(value)r",
                model=self.field_relation,
                field=self.search_field_name,
                value=value,
            )
        if isinstance(value, models.Model):
            return self.env._(
                "%(count)s → %(names)s", count=len(value), names=value.display_name
            )
        return str(value)[:PREVIEW_MAX_CHARS]

    def _render_preview_column(self, sample):
        # Preview this line's column independently via `_get_column_values`
        # - never call `template._get_table_info()` from a line compute, or
        # opening a template with N "lines" columns becomes an O(N^2)
        # extraction every time the dialog renders.
        raw = self._get_column_values(sample)
        if not raw:
            return self.env._("No match.")
        rows = [self.env._("%s value(s):", len(raw))]
        for index, item in enumerate(raw[:PREVIEW_MAX_ROWS], start=1):
            try:
                processed = self._process_value(item)
            except Exception as err:  # pylint: disable=W8138
                processed = self.env._("⚠ %s", err)
            rows.append(f"{index:>3}. {item!r} → {processed!r}")
        if len(raw) > PREVIEW_MAX_ROWS:
            rows.append(self.env._("… and %s more", len(raw) - PREVIEW_MAX_ROWS))
        return "\n".join(rows)[:PREVIEW_MAX_CHARS]
