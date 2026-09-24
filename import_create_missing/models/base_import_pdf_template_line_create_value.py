# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

#: Same mapping `base.import.pdf.template.line._get_fixed_field_name_ttype_
#: mapped()` uses for ITS OWN typed fixed_value_* fields - kept here only
#: as the set of ttypes a plain-Char `fixed_value` can be reasonably cast
#: into. `many2one`/`reference`/`one2many` are handled separately (see
#: `_to_create_value()`), never through this cast.
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
        help="The template line whose 'Create New Document if Not Found' "
        "this row belongs to - the same on every row, including a nested "
        "row under a one2many field's own Row Values (see `parent_id`); "
        "only `parent_id`/`model` change what MODEL a nested row targets.",
    )
    template_id = fields.Many2one(related="line_id.template_id", store=True)
    #: Set only on a nested row - one that fills a field on a record of
    #: an ANCESTOR row's one2many field (`parent_id.child_value_ids`),
    #: rather than directly on the document the template line itself
    #: creates. e.g. a top-level row targeting `product.product.seller_ids`
    #: (a one2many) has no `parent_id`; the rows that fill in each
    #: `product.supplierinfo`'s own `partner_id`/`price`/... - one
    #: `product.supplierinfo` record per one2many command - are its
    #: `child_value_ids`, and each of THOSE has `parent_id` set to it.
    parent_id = fields.Many2one(
        comodel_name="base.import.pdf.template.line.create.value",
        string="Parent value",
        ondelete="cascade",
    )
    child_value_ids = fields.One2many(
        comodel_name="base.import.pdf.template.line.create.value",
        inverse_name="parent_id",
        string="Row Values",
        copy=True,
        help="Only meaningful when Field is a one2many - one field-value "
        "per field of the one2many's own model (e.g. a vendor's "
        "partner_id/price/min_qty), the same Field/Type/Value/Pattern "
        "shape as this table itself. Each Variable row here is extracted "
        "fresh from the whole document (not tied to this line's own "
        "row position) and rows are paired across every Variable child "
        "by JSONPath/Pattern match position - see the README.",
    )
    #: All models `field_id`'s domain should match against: `model` itself
    #: plus any model it delegates fields from via `_inherits` (e.g.
    #: `product.product` → `product.template`), recursively. Split into
    #: its own stored-nowhere compute (rather than building the domain
    #: string in Python) so the view can express it as an ordinary
    #: many2one domain - `[('model_id', 'in', candidate_model_ids)]` -
    #: without a server round-trip beyond the normal onchange.
    candidate_model_ids = fields.Many2many(
        comodel_name="ir.model",
        compute="_compute_candidate_model_ids",
    )
    #: The model of the document being CREATED. For a top-level row, this
    #: is the template line's own linked model (`line_id.field_relation`)
    #: - not the line's `model` (the template's header/lines model the
    #: line itself lives on). For a nested row (`parent_id` set), it's
    #: the comodel of the ANCESTOR row's one2many field instead -
    #: `parent_id.field_relation`.
    model = fields.Char(compute="_compute_model", store=True)
    field_id = fields.Many2one(
        comodel_name="ir.model.fields",
        string="Field",
        domain="[('model_id', 'in', candidate_model_ids), ('store', '=', True)]",
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
        "as the line's own Pattern. For a row belonging to this line's "
        "own document (not nested under a one2many), evaluated once per "
        "row of this line's table (or once for a header line), same "
        "alignment as the line's own Pattern. For a row nested under a "
        "one2many field, evaluated once per match against the WHOLE "
        "document instead - see `child_value_ids`."
    )
    value_summary = fields.Char(
        compute="_compute_value_summary",
        help="What this row actually does, summarized for the compact "
        "list - since Value/Pattern (and, if installed, JSONPath) are "
        "mutually exclusive per row, showing all of them as columns at "
        "once is confusing; open a row to edit it.",
    )

    @api.model
    def _selection_reference_value(self):
        installed_models = (
            self.env["ir.model"]
            .sudo()
            .search([("transient", "=", False)], order="name asc")
        )
        return [(model.model, model.name) for model in installed_models]

    @api.depends("parent_id.field_relation", "line_id.field_relation")
    def _compute_model(self):
        for rec in self:
            rec.model = (
                rec.parent_id.field_relation
                if rec.parent_id
                else rec.line_id.field_relation
            )

    def _model_and_delegated_parents(self, model_name):
        """`model_name` plus every model it delegates fields from via
        `_inherits` (e.g. `product.product` → `product.template`),
        recursively - the set of models `ir.model.fields.model_id` can
        legitimately be on for a field that's genuinely usable on
        `model_name` (a delegated field's `ir.model.fields` record is
        owned by the DEFINING model, never the delegating one)."""
        seen = set()
        to_visit = [model_name]
        while to_visit:
            name = to_visit.pop()
            if name in seen or name not in self.env:
                continue
            seen.add(name)
            to_visit.extend(self.env[name]._inherits.keys())
        return list(seen)

    @api.depends("model")
    def _compute_candidate_model_ids(self):
        for rec in self:
            if not rec.model:
                rec.candidate_model_ids = False
                continue
            model_names = rec._model_and_delegated_parents(rec.model)
            rec.candidate_model_ids = (
                self.env["ir.model"].sudo().search([("model", "in", model_names)])
            )

    def _value_summary_text(self):
        self.ensure_one()
        if not self.field_id:
            return False
        if self.field_ttype == "one2many":
            return self.env._("%s row template(s)", len(self.child_value_ids))
        if self.value_type == "fixed":
            if self.field_ttype in ("many2one", "reference"):
                return self.fixed_value_ref.display_name if self.fixed_value_ref else False
            return self.fixed_value
        # Variable: prefer JSONPath when a bridge module (e.g.
        # `import_create_missing_xberg`) has added it and it's set -
        # `getattr` rather than `self.xberg_jsonpath` directly since the
        # field doesn't exist at all without that module installed.
        jsonpath = getattr(self, "xberg_jsonpath", False)
        if jsonpath:
            return self.env._("JSONPath: %s", jsonpath)
        if self.pattern:
            return self.env._("Pattern: %s", self.pattern)
        return self.env._("⚠ No pattern/JSONPath set.")

    @api.depends(
        "field_id",
        "field_ttype",
        "value_type",
        "fixed_value",
        "fixed_value_ref",
        "pattern",
        "child_value_ids",
    )
    def _compute_value_summary(self):
        for rec in self:
            rec.value_summary = rec._value_summary_text()

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

    def _to_create_value(self, raw, text=None):
        """Convert one raw extracted value (or, for a `fixed` row,
        `raw` is ignored) into the value to put in the new document's
        create-vals for `field_name`. Returns `None` when there is
        nothing usable - the caller skips the key entirely rather than
        writing an empty/false value over a default.

        `text` (the whole extracted document) is only used for a
        `one2many` row - see `_extract_one2many_commands()` - and is
        `None` whenever the caller doesn't have it (a preview render
        never reaches this method at all, so in practice this is only
        `None` if a future caller adds one without threading it through).
        """
        self.ensure_one()
        if self.field_ttype == "one2many":
            commands = self._extract_one2many_commands(text)
            return commands or None
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

    def _extract_one2many_commands(self, text):
        """`(0, 0, vals)` create commands for this row's one2many field,
        one per row of `child_value_ids` - unlike every other field on
        this line, a one2many's own rows are extracted fresh from the
        WHOLE document (`text`), not tied to this line's own row
        position: there is no general way to address "the vendors that
        belong to THIS row" within a flat/table document without a
        per-row-relative pattern language this module doesn't have -
        see the README's "Nested one2many fields" section. Every
        `child_value_ids` row's `Variable` extraction is instead paired
        by MATCH POSITION across the whole document: the 3rd vendor
        name goes with the 3rd vendor price, and so on.

        Returns `[]` (not `None`) when there is nothing to create -
        callers treat both the same way (skip the key), but zero
        `child_value_ids` or zero matches is not itself an error worth
        logging, unlike a ragged column.
        """
        self.ensure_one()
        if not text or not self.child_value_ids:
            return []
        variable_children = self.child_value_ids.filtered(
            lambda c: c.field_name
            and c.value_type == "variable"
            and c._has_variable_source()
        )
        row_count = None
        columns = {}
        for child in variable_children:
            values = child._extract_column(text)
            columns[child.id] = values
            if row_count is None:
                row_count = len(values)
            elif len(values) != row_count:
                _logger.warning(
                    "New Document Values row %s: Row Values row %s (%s) "
                    "extracted %s value(s) but another Row Values row on "
                    "the same field extracted %s - skipping every row of "
                    "%s.",
                    self.id,
                    child.id,
                    child.field_name,
                    len(values),
                    row_count,
                    self.field_name,
                )
                return []
        if row_count is None:
            # No Variable children at all - a one2many made entirely of
            # Fixed rows describes exactly one record, not zero.
            row_count = 1
        commands = []
        for index in range(row_count):
            row_vals = {}
            for child in self.child_value_ids.sorted("sequence"):
                if not child.field_name:
                    continue
                if child in variable_children:
                    child_raw = columns[child.id][index]
                else:
                    child_raw = None
                value = child._to_create_value(child_raw, text=text)
                if value is None:
                    continue
                row_vals[child.field_name] = value
            if row_vals:
                commands.append((0, 0, row_vals))
        return commands

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
