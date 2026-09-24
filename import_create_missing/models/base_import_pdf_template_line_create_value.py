# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

#: Same mapping `base.import.pdf.template.line._get_fixed_field_name_ttype_
#: mapped()` uses for ITS OWN typed fixed_value_* fields - kept here only
#: as the set of ttypes a plain-Char `fixed_value` can be reasonably cast
#: into. `many2one`/`reference` are handled separately via `fixed_value_ref`
#: (see `_to_create_value()`), never through this cast.
_CASTABLE_FIXED_TTYPES = ("char", "text", "html", "integer", "float", "boolean", "json")


class BaseImportPdfTemplateLineCreateValue(models.Model):
    _name = "base.import.pdf.template.line.create.value"
    _description = "New Document Value for a Base Import Pdf Template Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    line_id = fields.Many2one(
        comodel_name="base.import.pdf.template.line",
        string="Template line",
        required=True,
        ondelete="cascade",
    )
    template_id = fields.Many2one(related="line_id.template_id", store=True)
    #: The model of the document being CREATED - the line's own linked
    #: model (`field_relation`), not the line's `model` (the template's
    #: header/lines model the line itself lives on). e.g. a line matching
    #: `product.product` on a purchase.order.line template has
    #: `model = "purchase.order.line"` but this is `"product.product"`.
    model = fields.Char(related="line_id.field_relation", store=True)
    field_id = fields.Many2one(
        comodel_name="ir.model.fields",
        string="Field",
        domain="[('model_id.model', '=', model), ('store', '=', True)]",
        required=True,
        ondelete="cascade",
    )
    field_name = fields.Char(related="field_id.name")
    field_ttype = fields.Selection(related="field_id.ttype")
    field_relation = fields.Char(related="field_id.relation")
    value_type = fields.Selection(
        selection=[("fixed", "Fixed"), ("variable", "Variable")],
        default="variable",
        required=True,
        string="Type",
    )
    fixed_value = fields.Char(
        string="Value",
        help="Used for every field type except many2one/reference, where "
        "the record picker below is used instead. Converted according to "
        "the field's own type (integer, float, boolean, ...).",
    )
    fixed_value_ref = fields.Reference(
        selection="_selection_reference_value",
        string="Value",
        help="The fixed record to set, for a many2one field.",
    )
    pattern = fields.Char(
        help="Regular expression matched against the extracted text, same "
        "as the line's own Pattern. Evaluated once per row of this line's "
        "table (or once for a header line), same alignment as the line's "
        "own Pattern - a row whose Pattern misses here contributes no "
        "value for this field."
    )

    @api.model
    def _selection_reference_value(self):
        installed_models = (
            self.env["ir.model"]
            .sudo()
            .search([("transient", "=", False)], order="name asc")
        )
        return [(model.model, model.name) for model in installed_models]

    def _has_variable_source(self):
        """Whether a `variable` row has anything to actually extract with.
        Split out as its own method (rather than inlined where it's used)
        so a module adding another extraction seam - e.g.
        `import_create_missing_xberg`'s `xberg_jsonpath` - can widen this
        instead of duplicating the row-skip logic around it."""
        self.ensure_one()
        return bool(self.pattern)

    def _proxy_line_vals(self):
        """The values used to build `_proxy_line()` - split out so a
        bridge module (e.g. `import_create_missing_xberg`) can extend it
        with its own extraction-seam fields (`xberg_jsonpath`, ...)
        without repeating the rest of this method."""
        self.ensure_one()
        line = self.line_id
        return {
            "template_id": line.template_id.id,
            "related_model": line.related_model,
            "field_id": self.field_id.id,
            "pattern": self.pattern,
            "value_type": "variable",
            "decimal_separator": line.decimal_separator,
            "thousand_separator": line.thousand_separator,
            "date_time_format": line.date_time_format,
        }

    def _proxy_line(self):
        """An in-memory `base.import.pdf.template.line` standing in for
        this row, so extraction and post-processing (`_get_column_values`,
        `_process_value`, and any extraction-mode override on top of them -
        e.g. `import_via_xberg`'s JSONPath narrowing) run through the
        line's own existing code instead of a parallel copy of it here."""
        self.ensure_one()
        return self.env["base.import.pdf.template.line"].new(self._proxy_line_vals())

    def _extract_column(self, text):
        """This row's own column of raw (unprocessed) values, one per row
        of the line's table - same shape and alignment as
        `line._get_column_values(text)`. The extension point a bridge
        module overrides to add another pattern language (mirrors
        `base.import.pdf.template.line._get_column_values()` itself)."""
        self.ensure_one()
        if not self._has_variable_source():
            return []
        return self._proxy_line()._get_column_values(text)

    def _extract_header(self, text):
        """Same idea as `_extract_column()`, but for a `header` line: a
        single value rather than one per table row."""
        self.ensure_one()
        values = self._extract_column(text)
        return values[0] if values else False

    def _to_create_value(self, raw):
        """Convert one raw extracted value (or, for a `fixed` row,
        `raw` is ignored) into the value to put in the new document's
        create-vals for `field_name`. Returns `None` when there is
        nothing usable - the caller skips the key entirely rather than
        writing an empty/false value over a default."""
        self.ensure_one()
        if self.value_type == "fixed":
            return self._fixed_create_value()
        if not raw:
            return None
        proxy = self._proxy_line()
        if self.field_ttype == "many2one":
            record = self.env[self.field_relation].search(
                [(self.env[self.field_relation]._rec_name, "=", raw)], limit=1
            )
            return record.id if record else None
        # `_without_pattern()` still runs `_process_value()`'s post-
        # processing tail (date/float conversion, mapped_ids,
        # search_field_id, default_value) without re-applying `pattern` -
        # `raw` already came out of `_extract_column()`, which applied it.
        value = proxy._without_pattern()._process_value(raw)
        if isinstance(value, models.Model):
            return value.id if value else None
        return value if value not in (False, None) else None

    def _fixed_create_value(self):
        self.ensure_one()
        if self.field_ttype in ("many2one", "reference"):
            return self.fixed_value_ref.id if self.fixed_value_ref else None
        if self.fixed_value in (False, None, ""):
            return None
        if self.field_ttype not in _CASTABLE_FIXED_TTYPES:
            return self.fixed_value
        if self.field_ttype == "integer":
            try:
                return int(self.fixed_value)
            except ValueError:
                _logger.warning(
                    "New Document Values row %s: %r is not a valid integer "
                    "for field %s.",
                    self.id,
                    self.fixed_value,
                    self.field_name,
                )
                return None
        if self.field_ttype == "float":
            try:
                return float(self.fixed_value)
            except ValueError:
                _logger.warning(
                    "New Document Values row %s: %r is not a valid float "
                    "for field %s.",
                    self.id,
                    self.fixed_value,
                    self.field_name,
                )
                return None
        if self.field_ttype == "boolean":
            return self.fixed_value.strip().lower() in ("1", "true", "yes", "y")
        return self.fixed_value
