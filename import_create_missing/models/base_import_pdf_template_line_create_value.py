# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from __future__ import annotations

import json
import logging
from collections.abc import Collection, Iterable
from typing import Any

from odoo import api, fields, models

from .create_field_spec import (
    FIXED_VALUE_FIELD,
    CreateFieldSpec,
    fields_with_defaults,
    fixed_value_kind,
    required_field_names,
    required_field_specs,
)

_logger = logging.getLogger(__name__)


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
        "shape as this table itself. Pre-filled with that model's own "
        "required fields the moment you pick the one2many. Each Variable "
        "row here is extracted fresh from the whole document (not tied to "
        "this line's own row position) and rows are paired across every "
        "Variable child by JSONPath/Pattern match position - see the "
        "README.",
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
        selection=[
            ("fixed", "Fixed"),
            ("variable", "Variable"),
            ("odoo_default", "Odoo Default"),
        ],
        default="variable",
        required=True,
        string="Type",
        help="Fixed: always this value. Variable: extracted from the "
        "document with the Pattern (or JSONPath) below. Odoo Default: "
        "leave the field out of the create entirely, so Odoo applies its "
        "own default - used for a required field whose default is "
        "computed at creation time (a date/datetime that means 'now'), "
        "where snapshotting a value into the template would be wrong.",
    )
    #: Which typed `fixed_value_*` column this row's `Fixed` value lives
    #: in - see `create_field_spec.FIXED_VALUE_FIELD`. Drives which single
    #: input the form shows, so the view never has to repeat the
    #: ttype-to-widget mapping that Python already owns.
    fixed_value_kind = fields.Selection(
        selection=[
            ("char", "Text"),
            ("boolean", "Boolean"),
            ("integer", "Integer"),
            ("float", "Float"),
            ("selection", "Selection"),
            ("date", "Date"),
            ("datetime", "Datetime"),
            ("record", "Record"),
        ],
        compute="_compute_fixed_value_kind",
    )
    fixed_value = fields.Char(
        string="Value",
        help="Used for a text/html/json field. Other field types get a "
        "typed input of their own (a checkbox, a number, a dropdown, a "
        "date picker or a record picker).",
    )
    fixed_value_boolean = fields.Boolean(string="Value")
    fixed_value_integer = fields.Integer(string="Value")
    fixed_value_float = fields.Float(string="Value")
    fixed_value_date = fields.Date(string="Value")
    fixed_value_datetime = fields.Datetime(string="Value")
    fixed_value_selection_id = fields.Many2one(
        comodel_name="ir.model.fields.selection",
        string="Value",
        domain="[('field_id', '=', field_id)]",
        ondelete="cascade",
        help="The selection option to set, for a selection field.",
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
    is_required = fields.Boolean(
        compute="_compute_is_required",
        string="Required",
        help="Whether the document being created genuinely requires this "
        "field - i.e. `create()` would reject the record without it.",
    )
    has_odoo_default = fields.Boolean(
        compute="_compute_has_odoo_default",
        string="Odoo has a default",
        help="Whether Odoo itself would fill this field in on create(). "
        "`Odoo Default` only means anything when this is set - otherwise "
        "the field is simply left unset and the document is rejected.",
    )
    has_missing_required = fields.Boolean(
        compute="_compute_has_missing_required",
        string="Missing",
        help="This row (or, for a one2many, one of its Row Values) is a "
        "required field with no Odoo default and nothing set - the "
        "document creation will fail unless it is filled in.",
    )

    @api.model
    def _selection_reference_value(self):
        installed_models = (
            self.env["ir.model"]
            .sudo()
            .search([("transient", "=", False)], order="name asc")
        )
        return [(model.model, model.name) for model in installed_models]

    @api.model_create_multi
    def create(self, vals_list):
        """Let a nested row inherit its parent's `line_id`.

        `line_id` is required on every row, nested or not (see its help),
        but the Row Values table auto-populated by
        `_onchange_field_id_children()` is built before the outer row
        exists - there is no `default_line_id` for the client to hand the
        nested rows, and on an unsaved line there is no id to hand either.
        """
        for vals in vals_list:
            if not vals.get("line_id") and vals.get("parent_id"):
                vals["line_id"] = self.browse(vals["parent_id"]).line_id.id
        return super().create(vals_list)

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

    @api.depends("field_ttype", "field_id")
    def _compute_fixed_value_kind(self):
        for rec in self:
            if not rec.field_id:
                rec.fixed_value_kind = False
                continue
            # `.sudo()`: `ir.model.fields.selection` is unreadable to
            # `base.group_user`, and this compute runs for any user who can
            # so much as look at a template.
            has_options = bool(rec.field_id.sudo().selection_ids)
            rec.fixed_value_kind = (
                fixed_value_kind(rec.field_ttype, has_options) or False
            )

    # -------------------------------------------------------------------
    # Required-field discovery
    # -------------------------------------------------------------------

    def _required_scope_exclude(self) -> tuple[str, ...]:
        """Field names that must NOT be reported as missing (nor
        auto-added) in this row's own scope.

        A nested row's scope is its parent one2many's comodel, whose
        inverse many2one is set by the one2many command itself; a
        top-level row's scope is the document being created, whose search
        field is pre-filled with the value that missed (see
        `base.import.pdf.template.line._create_missing_prefill_field_name()`).
        """
        self.ensure_one()
        if self.parent_id:
            inverse = self.parent_id.field_id.sudo().relation_field
            return (inverse,) if inverse else ()
        prefill = self.line_id._create_missing_prefill_field_name()
        return (prefill,) if prefill else ()

    @api.depends(
        "model",
        "field_name",
        "parent_id.field_id",
        "line_id.search_field_id",
        "line_id.search_subfield_id",
        "line_id.field_id",
    )
    def _compute_is_required(self):
        names_by_model: dict[tuple[str, tuple[str, ...]], frozenset[str]] = {}
        for rec in self:
            model_name = rec.model
            if not model_name or model_name not in rec.env:
                rec.is_required = False
                continue
            key = (model_name, rec._required_scope_exclude())
            if key not in names_by_model:
                names_by_model[key] = required_field_names(
                    rec.env[model_name], exclude=key[1]
                )
            rec.is_required = rec.field_name in names_by_model[key]

    @api.depends("model", "field_name")
    def _compute_has_odoo_default(self):
        by_model: dict[str, list] = {}
        for rec in self:
            by_model.setdefault(rec.model or "", []).append(rec)
        for model_name, recs in by_model.items():
            if not model_name or model_name not in self.env:
                for rec in recs:
                    rec.has_odoo_default = False
                continue
            defaulted = fields_with_defaults(
                self.env[model_name],
                [rec.field_name for rec in recs if rec.field_name],
            )
            for rec in recs:
                rec.has_odoo_default = rec.field_name in defaulted

    @api.model
    def _value_depends(self) -> tuple[str, ...]:
        """Every field that can change what a row actually contributes -
        the `@api.depends` of the summary and of the missing-value flag.
        Built from `FIXED_VALUE_FIELD` plus `_variable_source_fields()` so
        adding a typed column or another extraction seam (e.g.
        `import_create_missing_xberg`'s JSONPath) updates both computes
        without touching either decorator."""
        return (
            "field_id",
            "field_ttype",
            "value_type",
            "child_value_ids",
            "has_odoo_default",
            *FIXED_VALUE_FIELD.values(),
            *self._variable_source_fields(),
        )

    def _variable_source_fields(self) -> tuple[str, ...]:
        """The fields a `variable` row can be driven by. The seam a bridge
        module widens - see `import_create_missing_xberg`, which adds
        `xberg_jsonpath` - so `_has_variable_source()` and every
        `@api.depends` built on it pick the new source up together."""
        return ("pattern",)

    def _has_variable_source(self) -> bool:
        """Whether a `variable` row has anything to actually extract with."""
        self.ensure_one()
        return any(self[name] for name in self._variable_source_fields())

    def _has_value(self) -> bool:
        """Whether this row will genuinely contribute something to the
        document being created - the test behind `has_missing_required`."""
        self.ensure_one()
        if self.value_type == "odoo_default":
            # Only a real default counts. Deferring to one that does not
            # exist leaves the field unset and the document rejected, so
            # it is the opposite of "handled" - and must not silence the
            # warning that says so.
            return self.has_odoo_default
        if self.field_ttype == "one2many":
            return bool(self.child_value_ids)
        if self.value_type == "fixed":
            return self._fixed_create_value() is not None
        return self._has_variable_source()

    @api.model
    def _missing_required_labels(
        self,
        rows: models.Model,
        model_name: str,
        exclude: Collection[str] = (),
        prefix: str = "",
    ) -> list[str]:
        """Human labels for every required field of `model_name` that
        `rows` leave genuinely unset - i.e. no Odoo default to fall back
        on and no row that contributes a value - recursing into each
        one2many row's own Row Values.

        Shared by the line's warning banner and the per-row `Missing`
        flag so the two can never disagree about what counts as missing.
        """
        if not model_name or model_name not in self.env:
            return []
        rows_by_name: dict[str, models.Model] = {}
        for row in rows:
            if row.field_name and row.field_name not in rows_by_name:
                rows_by_name[row.field_name] = row
        labels: list[str] = []
        for spec in required_field_specs(self.env[model_name], exclude=exclude):
            if spec.has_default:
                continue
            row = rows_by_name.get(spec.name)
            if row is not None and row._has_value():
                continue
            labels.append(f"{prefix}{spec.label}")
        for row in rows:
            if row.field_ttype != "one2many" or not row.child_value_ids:
                # An empty one2many creates no sub-record at all, so its
                # comodel's required fields are not needed yet.
                continue
            inverse = row.field_id.sudo().relation_field
            labels += self._missing_required_labels(
                row.child_value_ids,
                row.field_relation,
                exclude=(inverse,) if inverse else (),
                prefix=f"{prefix}{row.field_id.field_description} › ",
            )
        return labels

    def _required_spec(self, cache: dict | None = None) -> CreateFieldSpec | None:
        """The `CreateFieldSpec` for this row's OWN field, or `None` when
        the field isn't required in this row's scope. `cache` (keyed by
        model + scope) keeps a table of rows from re-running
        `default_get()` once per row."""
        self.ensure_one()
        if not self.field_name or not self.model or self.model not in self.env:
            return None
        key = (self.model, self._required_scope_exclude())
        if cache is None:
            cache = {}
        if key not in cache:
            cache[key] = {
                spec.name: spec
                for spec in required_field_specs(self.env[key[0]], exclude=key[1])
            }
        return cache[key].get(self.field_name)

    def _is_missing_required(self, cache: dict | None = None) -> bool:
        """Whether this row leaves something the document genuinely needs
        unset - itself, or (for a one2many) inside its Row Values."""
        self.ensure_one()
        if not self.field_id:
            return False
        if self.field_ttype == "one2many" and self.child_value_ids:
            inverse = self.field_id.sudo().relation_field
            if self._missing_required_labels(
                self.child_value_ids,
                self.field_relation,
                exclude=(inverse,) if inverse else (),
            ):
                return True
        spec = self._required_spec(cache)
        if spec is None or spec.has_default:
            # Not required here, or Odoo will fill it in itself.
            return False
        return not self._has_value()

    @api.depends(
        lambda self: (
            *self._value_depends(),
            "model",
            "child_value_ids.has_missing_required",
        )
    )
    def _compute_has_missing_required(self):
        cache: dict = {}
        for rec in self:
            rec.has_missing_required = rec._is_missing_required(cache)

    # -------------------------------------------------------------------
    # Auto-population
    # -------------------------------------------------------------------

    @api.model
    def _row_vals_from_spec(
        self, spec: CreateFieldSpec, sequence: int = 10
    ) -> dict[str, Any]:
        """Create-vals for the row that fills `spec`.

        A required field Odoo has no default for becomes an empty
        `Variable` row - the user still has to say where the value comes
        from, which is the whole point of surfacing it. One Odoo DOES
        default becomes a `Fixed` row pre-set to that default, so the
        default is visible and editable rather than invisible; except when
        the default cannot be meaningfully frozen into a template (a
        date/datetime default almost always means "now"), where the row
        says `Odoo Default` and leaves the field out of the create.
        """
        vals: dict[str, Any] = {"field_id": spec.field_id, "sequence": sequence}
        kind = fixed_value_kind(spec.ttype)
        if not spec.has_default or spec.ttype == "one2many":
            vals["value_type"] = "variable"
            return vals
        if kind in (None, "date", "datetime"):
            vals["value_type"] = "odoo_default"
            return vals
        vals["value_type"] = "fixed"
        if kind == "record":
            if spec.comodel and spec.default:
                vals["fixed_value_ref"] = f"{spec.comodel},{int(spec.default)}"
            else:
                vals["value_type"] = "odoo_default"
        elif kind == "selection":
            option = (
                self.env["ir.model.fields.selection"]
                .sudo()
                .search(
                    [("field_id", "=", spec.field_id), ("value", "=", spec.default)],
                    limit=1,
                )
            )
            if option:
                vals["fixed_value_selection_id"] = option.id
            else:
                vals["value_type"] = "odoo_default"
        elif kind == "char":
            vals["fixed_value"] = (
                json.dumps(spec.default)
                if spec.ttype == "json"
                else str(spec.default)
            )
        else:
            vals[FIXED_VALUE_FIELD[kind]] = spec.default
        return vals

    @api.model
    def _required_rows_vals(
        self,
        model_name: str,
        existing: Iterable[str] = (),
        exclude: Collection[str] = (),
        start_sequence: int = 0,
    ) -> list[dict[str, Any]]:
        """Create-vals for every required field of `model_name` that
        `existing` (field names already in the table) doesn't cover."""
        if not model_name or model_name not in self.env:
            return []
        covered = set(existing)
        sequence = start_sequence
        vals_list: list[dict[str, Any]] = []
        for spec in required_field_specs(self.env[model_name], exclude=exclude):
            if spec.name in covered:
                continue
            sequence += 10
            vals_list.append(self._row_vals_from_spec(spec, sequence))
        return vals_list

    @api.onchange("field_id")
    def _onchange_field_id_children(self):
        """Pre-fill a one2many row's Row Values with its comodel's own
        required fields, the moment the one2many is picked - the nested
        half of what `base.import.pdf.template.line._onchange_create_missing()`
        does for the outer table. Only ever fills an EMPTY Row Values
        table, so a user's own rows are never disturbed."""
        for rec in self:
            if rec.field_ttype != "one2many" or rec.child_value_ids:
                continue
            if not rec.field_relation or rec.field_relation not in rec.env:
                continue
            inverse = rec.field_id.sudo().relation_field
            vals_list = rec._required_rows_vals(
                rec.field_relation, exclude=(inverse,) if inverse else ()
            )
            if vals_list:
                rec.child_value_ids = [
                    fields.Command.create(vals) for vals in vals_list
                ]

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------

    def _fixed_value_display(self):
        """This row's `Fixed` value, rendered for the compact list."""
        self.ensure_one()
        kind = self.fixed_value_kind
        if not kind:
            return False
        if kind == "record":
            return self.fixed_value_ref.display_name if self.fixed_value_ref else False
        if kind == "selection":
            option = self.fixed_value_selection_id.sudo()
            return option.name if option else False
        if kind == "boolean":
            return self.env._("Yes") if self.fixed_value_boolean else self.env._("No")
        value = self[FIXED_VALUE_FIELD[kind]]
        if value in (False, None, ""):
            return False
        return str(value)

    def _value_summary_text(self):
        self.ensure_one()
        if not self.field_id:
            return False
        if self.value_type == "odoo_default":
            return (
                self.env._("Odoo default")
                if self.has_odoo_default
                else self.env._("⚠ Odoo has no default for this field.")
            )
        if self.field_ttype == "one2many":
            return self.env._("%s row template(s)", len(self.child_value_ids))
        if self.value_type == "fixed":
            return self._fixed_value_display() or self.env._("⚠ No value set.")
        for name in self._variable_source_fields():
            value = self[name]
            if value:
                return self.env._(
                    "%(label)s: %(value)s",
                    label=self._fields[name].string,
                    value=value,
                )
        return self.env._("⚠ No pattern/JSONPath set.")

    @api.depends(lambda self: self._value_depends())
    def _compute_value_summary(self):
        for rec in self:
            rec.value_summary = rec._value_summary_text()

    # -------------------------------------------------------------------
    # Extraction
    # -------------------------------------------------------------------

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
        if self.value_type == "odoo_default":
            # Deliberately absent from the create-vals: that IS how Odoo's
            # own default gets applied.
            return None
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
        """This row's `Fixed` value, in `create()` format - or `None` when
        nothing is set, so the caller leaves the key out entirely rather
        than writing an empty value over Odoo's own default."""
        self.ensure_one()
        kind = self.fixed_value_kind
        if not kind:
            return None
        if kind == "record":
            return self.fixed_value_ref.id if self.fixed_value_ref else None
        if kind == "selection":
            # `.sudo()` for the same reason the base module's own
            # `_get_fixed_value()` uses it: `ir.model.fields.selection` is
            # not readable by an ordinary user, and this runs mid-import.
            option = self.fixed_value_selection_id.sudo()
            return option.value if option else None
        if kind in ("boolean", "integer", "float"):
            # A deliberate False/0 is a real value here, not an omission.
            return self[FIXED_VALUE_FIELD[kind]]
        value = self[FIXED_VALUE_FIELD[kind]]
        if value in (False, None, ""):
            return None
        if kind == "char" and self.field_ttype == "json":
            try:
                return json.loads(value)
            except ValueError:
                _logger.warning(
                    "New Document Values row %s: %r is not valid JSON for "
                    "field %s.",
                    self.id,
                    value,
                    self.field_name,
                )
                return None
        return value

    # -------------------------------------------------------------------
    # Migration
    # -------------------------------------------------------------------

    @api.model
    def _migrate_legacy_fixed_value(self):
        """Move pre-1.1.0 `Fixed` values out of the single Char column
        into the typed one for their field type.

        Before 1.1.0 every fixed value was stored as text in
        `fixed_value` and cast at import time; a boolean read "True", a
        selection held its raw key. The casts below are deliberately the
        OLD ones, so a template keeps meaning exactly what it meant
        before. Anything that doesn't parse is left in place and logged
        rather than silently dropped.
        """
        rows = self.search([("value_type", "=", "fixed"), ("fixed_value", "!=", False)])
        for row in rows:
            kind = row.fixed_value_kind
            raw = row.fixed_value
            if kind in (None, False, "char", "record"):
                continue
            vals = {}
            if kind == "boolean":
                vals["fixed_value_boolean"] = raw.strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "y",
                )
            elif kind == "integer":
                try:
                    vals["fixed_value_integer"] = int(raw)
                except ValueError:
                    _logger.warning(
                        "New Document Values row %s: cannot migrate %r to an "
                        "integer value; left as text.", row.id, raw
                    )
                    continue
            elif kind == "float":
                try:
                    vals["fixed_value_float"] = float(raw)
                except ValueError:
                    _logger.warning(
                        "New Document Values row %s: cannot migrate %r to a "
                        "float value; left as text.", row.id, raw
                    )
                    continue
            elif kind == "selection":
                option = (
                    self.env["ir.model.fields.selection"]
                    .sudo()
                    .search(
                        [("field_id", "=", row.field_id.id), ("value", "=", raw)],
                        limit=1,
                    )
                )
                if not option:
                    _logger.warning(
                        "New Document Values row %s: %r is not an option of "
                        "%s; left as text.", row.id, raw, row.field_name
                    )
                    continue
                vals["fixed_value_selection_id"] = option.id
            elif kind in ("date", "datetime"):
                field = self._fields[FIXED_VALUE_FIELD[kind]]
                try:
                    vals[FIXED_VALUE_FIELD[kind]] = field.convert_to_cache(raw, row)
                except ValueError:
                    _logger.warning(
                        "New Document Values row %s: cannot migrate %r to a "
                        "%s value; left as text.", row.id, raw, kind
                    )
                    continue
            vals["fixed_value"] = False
            row.write(vals)
        return True
