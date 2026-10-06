# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final

from odoo import SUPERUSER_ID, api, fields, models
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

#: The context key holding this row's `create_value_ids` values, keyed by
#: this line's own id: `{line_id: {create_value_id: raw_value, ...} | None}`.
#: Set by `base.import.pdf.template._get_field_values()`/
#: `_get_field_values_from_table_item()` (via `with_context()`) for exactly
#: one row (or the header) at a time, and ONLY when
#: `wizard.base.import.pdf.upload.line._process_form()` is actually running
#: a real import - never during a preview/onchange render. Its absence is
#: what makes a search miss inert everywhere except a real import, without
#: `create_missing` itself needing to know the difference.
#:
#: On a `lines` line the inner dict also carries the per-row values of each
#: one2many row's own Variable Row Values, keyed by THEIR ids - see
#: `base.import.pdf.template._extract_create_missing_columns()`.
CREATE_MISSING_VALUES_KEY = "import_create_missing_values"

#: The whole extracted document, set alongside `CREATE_MISSING_VALUES_KEY`
#: (same lifetime/guard). Only a `header` line's one2many rows need it:
#: with a single row to begin with, their Row Values search the WHOLE
#: document and pair their matches by position (see
#: `base.import.pdf.template.line.create.value._extract_one2many_
#: commands()`). A `lines` line's one2many rows are instead aligned to the
#: line's own table rows, like every other column.
CREATE_MISSING_TEXT_KEY = "import_create_missing_text"

#: One2many fields always offered in New Document Values when the line
#: creates a record of the given model, although nothing makes them
#: required. A product created without a vendor row is one no later
#: import can find by vendor code, so every such import would create a
#: fresh duplicate - see `_create_missing_always_one2many()`.
_ALWAYS_OFFERED_ONE2MANY: Final[Mapping[str, tuple[str, ...]]] = {
    "product.product": ("seller_ids",),
    "product.template": ("seller_ids",),
}


class BaseImportPdfTemplateLine(models.Model):
    _inherit = "base.import.pdf.template.line"

    create_missing = fields.Boolean(
        string="Create New Document if Not Found",
        help="When this line's search (Search field / Search subfield "
        "above) misses, create the missing document instead of leaving "
        "the line unresolved - filled in from New Document Values below. "
        "Only meaningful when Field is a many2one with a Search field set; "
        "harmless but inert otherwise.",
    )
    #: Top-level rows only. Every row, nested or not, carries `line_id` (so
    #: a line's deletion cascades to all of them), but a nested row fills a
    #: field of its parent one2many's COMODEL - showing it here, beside the
    #: document's own fields, made it look like one of them, and feeding it
    #: to the document's own `create()` is what used to fail outright
    #: ("Invalid field 'partner_id' on model 'product.product"). Nested rows
    #: are reached through their parent row's `child_value_ids`.
    create_value_ids = fields.One2many(
        comodel_name="base.import.pdf.template.line.create.value",
        inverse_name="line_id",
        domain=[("parent_id", "=", False)],
        string="New Document Values",
        copy=True,
    )
    create_missing_warning = fields.Text(
        compute="_compute_create_missing_warning",
        help="What still stands between this line and a document it can "
        "actually create: required fields nothing fills in yet, and any "
        "configuration that will not extract what it looks like it will. "
        "Advisory only - the line still saves, and the import simply "
        "fails to create that document (and logs why) until it is fixed.",
    )

    # -------------------------------------------------------------------
    # Warning banner
    # -------------------------------------------------------------------

    def _create_missing_warning_depends(self) -> tuple[str, ...]:
        """`@api.depends` of `create_missing_warning` - a method rather than
        a literal so a module adding its own configuration warnings (see
        `_create_missing_config_warnings()`) can add the fields they read."""
        return (
            "create_missing",
            "field_id",
            "search_field_id",
            "search_subfield_id",
            "create_value_ids",
            "create_value_ids.field_id",
            "create_value_ids.has_missing_required",
            "create_value_ids.child_value_ids",
        )

    def _create_missing_config_warnings(self) -> list[str]:
        """Configuration problems worth a line in the warning banner - rows
        that are filled in, but will not extract what they appear to.
        Nothing here in the base module; an extraction engine's bridge
        module (e.g. `import_create_missing_xberg`) knows what "wrong"
        looks like for its own seams and extends this."""
        self.ensure_one()
        return []

    @api.depends(lambda self: self._create_missing_warning_depends())
    def _compute_create_missing_warning(self):
        create_value = self.env["base.import.pdf.template.line.create.value"]
        for line in self:
            messages: list[str] = []
            if line.create_missing and line.field_relation:
                prefill = line._create_missing_prefill_field_name()
                labels = create_value._missing_required_labels(
                    line._top_level_create_values(),
                    line.field_relation,
                    exclude=(prefill,) if prefill else (),
                )
                if labels:
                    messages.append(
                        self.env._(
                            "Required fields with no value yet: %s",
                            ", ".join(labels),
                        )
                    )
                messages += line._create_missing_config_warnings()
            line.create_missing_warning = "\n".join(messages) or False

    # -------------------------------------------------------------------
    # Auto-population
    # -------------------------------------------------------------------

    def _top_level_create_values(self):
        """The New Document Values rows that fill the document itself -
        `create_value_ids` already holds exactly those (see its domain);
        kept as a method so callers read as what they mean."""
        self.ensure_one()
        return self.create_value_ids

    def _create_missing_prefill_field_name(self) -> str | None:
        """The field `_prepare_create_missing_vals()` pre-fills with the
        very value the search missed, so re-importing the same document
        finds this record instead of creating a duplicate.

        Also the one required field that must NOT be auto-added to New
        Document Values, nor reported as missing: it is already handled,
        and a row for it would just shadow the searched value.
        """
        self.ensure_one()
        search_field = self.search_field_id
        if (
            search_field
            and not self.search_subfield_id
            and search_field.model_id.model == self.field_relation
            and search_field.ttype not in ("many2one", "many2many", "one2many")
        ):
            return search_field.name
        return None

    def _create_missing_always_one2many(self) -> tuple[str, ...]:
        """One2many fields to offer for the document this line creates even
        though none is required - see `_ALWAYS_OFFERED_ONE2MANY`. Only
        names that really are one2many fields of the target model are
        returned, so nothing breaks where `product` isn't installed."""
        self.ensure_one()
        model_name = self.field_relation
        if not model_name or model_name not in self.env:
            return ()
        model_fields = self.env[model_name]._fields
        return tuple(
            name
            for name in _ALWAYS_OFFERED_ONE2MANY.get(model_name, ())
            if name in model_fields and model_fields[name].type == "one2many"
        )

    def _required_create_value_vals(self) -> list[dict[str, Any]]:
        """Create-vals for the New Document Values rows this line still
        needs: one per required field of the document that no top-level
        row covers yet, then one per always-offered one2many (with its own
        required Row Values) that has no row yet. Never touches an
        existing row."""
        self.ensure_one()
        if not self.create_missing or not self.field_relation:
            return []
        create_value = self.env["base.import.pdf.template.line.create.value"]
        top_level = self._top_level_create_values()
        existing = {row.field_name for row in top_level if row.field_name}
        prefill = self._create_missing_prefill_field_name()
        start = max(top_level.mapped("sequence"), default=0)
        vals_list = create_value._required_rows_vals(
            self.field_relation,
            existing=existing,
            exclude=(prefill,) if prefill else (),
            start_sequence=start,
        )
        sequence = max((vals["sequence"] for vals in vals_list), default=start)
        for field_name in self._create_missing_always_one2many():
            if field_name in existing:
                continue
            sequence += 10
            row_vals = create_value._one2many_row_vals(
                self.field_relation, field_name, sequence
            )
            if row_vals:
                vals_list.append(row_vals)
        return vals_list

    @api.onchange("create_missing", "field_id", "search_field_id", "search_subfield_id")
    def _onchange_create_missing(self):
        """Keep New Document Values in step with the document being
        created: drop rows whose Field belongs to a model that is no
        longer the target (the user re-pointed Field at something else),
        then add a row for every required field that isn't covered yet.

        Rows the user added or edited are left exactly as they are - only
        rows that can no longer apply at all are removed.
        """
        create_value = self.env["base.import.pdf.template.line.create.value"]
        for line in self:
            if not line.create_missing:
                continue
            candidates = set(
                create_value._model_and_delegated_parents(line.field_relation)
                if line.field_relation
                else ()
            )
            stale = line._top_level_create_values().filtered(
                lambda row: row.field_id
                and row.field_id.model_id.model not in candidates
            )
            if stale:
                line.create_value_ids -= stale
            vals_list = line._required_create_value_vals()
            if vals_list:
                line.create_value_ids = [
                    fields.Command.create(vals) for vals in vals_list
                ]

    def action_add_required_create_values(self):
        """Fill in whatever is still missing - the manual counterpart of
        `_onchange_create_missing()`, for a line configured before this
        existed, or whose target model has since gained a required field.

        Adds top-level rows (required fields, always-offered one2many
        rows), and the required Row Values missing inside each one2many
        row that is already there. Never edits or removes a row; adding
        nothing is a no-op, not an error.
        """
        for line in self:
            vals_list = line._required_create_value_vals()
            if vals_list:
                line.create_value_ids = [
                    fields.Command.create(vals) for vals in vals_list
                ]
            for row in line._top_level_create_values():
                child_vals = row._missing_child_vals()
                if child_vals:
                    row.child_value_ids = [
                        fields.Command.create(vals) for vals in child_vals
                    ]
        return True

    # -------------------------------------------------------------------
    # Import
    # -------------------------------------------------------------------

    def _log_create_missing(self, message: str, func: str) -> None:
        """Record why a document was NOT created, where someone can find it.

        Written to `ir.logging` (Settings > Technical > Logging, Path =
        import_create_missing) on its OWN cursor - the same technique as
        a supplier-lookup module's own `_trace()` helper. A failed creation almost
        always goes on to fail the whole import (the line it was meant to
        fill is left empty), and that rolls back the import's transaction;
        a row written on the import's own cursor would vanish with it,
        leaving exactly the case that most needs explaining unexplained.
        """
        _logger.warning(message)
        try:
            db_name = self.env.cr.dbname
            with Registry(db_name).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["ir.logging"].create(
                    {
                        "name": "import_create_missing",
                        "type": "server",
                        "dbname": db_name,
                        "level": "WARNING",
                        "message": message,
                        "path": "import_create_missing",
                        "func": func,
                        "line": "0",
                    }
                )
        except Exception:
            _logger.exception("import_create_missing: failed to write an ir.logging entry")

    def _get_record_search_from_value(self, value):
        record = super()._get_record_search_from_value(value)
        if record or not value or not self.create_missing:
            return record
        row = self.env.context.get(CREATE_MISSING_VALUES_KEY)
        if row is None:
            # Not a real import (a preview/onchange render, or another
            # caller entirely) - never create anything outside
            # `wizard.base.import.pdf.upload.line._process_form()`.
            return record
        row = row.get(self.id)
        if row is None:
            # `_get_table_info()` found one of this line's New Document
            # Values columns didn't line up with the line's own rows, and
            # already logged why - nothing more to do here than fall
            # through to default_value/raw text, same as any other miss.
            return record
        vals = self._prepare_create_missing_vals(value, row)
        try:
            with self.env.cr.savepoint():
                record = self.env[self.field_relation].create(vals)
        except Exception as err:  # pylint: disable=W8138
            self._log_create_missing(
                f"Line {self.id}: failed to create a missing "
                f"{self.field_relation} record for {value!r}: {err}",
                "_get_record_search_from_value",
            )
            return self.env[self.field_relation]
        return record

    def _prepare_create_missing_vals(self, value, row):
        self.ensure_one()
        vals = {}
        text = self.env.context.get(CREATE_MISSING_TEXT_KEY)
        prefill_field_name = self._create_missing_prefill_field_name()
        if prefill_field_name:
            # Pre-fill the field the next import's search would look this
            # value up by, so re-importing the same document (or another
            # from the same source) finds this record instead of creating
            # a duplicate. A New Document Values row for the same field
            # (rare, but not forbidden) overrides this below.
            vals[prefill_field_name] = value
        for create_value in self._top_level_create_values().sorted("sequence"):
            if not create_value.field_name:
                continue
            create_value_value = create_value._to_create_value(
                row.get(create_value.id), text=text, row=row
            )
            if create_value_value is None:
                continue
            vals[create_value.field_name] = create_value_value
        return vals

    def _preview_depends(self):
        """Soft integration with `import_preview` - see the identical
        pattern (and its full explanation) on `import_via_xberg`'s
        `_preview_depends()`. `create_missing`/`create_value_ids` don't
        change what THIS line itself extracts, but they do change what a
        search miss on it results in, so the live preview should still
        refresh when either changes."""
        return super()._preview_depends() + ["create_missing", "create_value_ids"]
