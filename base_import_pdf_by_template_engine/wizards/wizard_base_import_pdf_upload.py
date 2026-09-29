# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from __future__ import annotations

import logging
import re

from psycopg2 import Error as Psycopg2Error

from odoo import exceptions, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: `odoo.tests.form.Form`'s own required-field assertions - there are two,
#: independent and differently worded. A TOP-LEVEL form's own `.save()`
#: goes through the general, recursive `_get_values('save')` (`odoo/tests/
#: form.py`, ~line 506): `f"{field_name} is a required field
#: ({view['modifiers'][field_name]})"` - bare field name, a trailing
#: modifiers dict. A one2many/many2many ROW's sub-form - `x2many.new()`,
#: what `_process_child_lines()`'s `with child_line.new() as line_form:`
#: uses - has its OWN, simpler `_get_save_values()` (~line 696):
#: `f"{field_name!r} is a required field"` - quoted, no dict. Both matched
#: here so either shape resolves to the field's real label instead of
#: this Python-internal phrasing showing up verbatim.
_REQUIRED_FIELD_RE = re.compile(
    r"^(?:'(?P<quoted>\w+)'|(?P<bare>\w+)) is a required field\b"
)


class WizardBaseImportPdfUploadLine(models.TransientModel):
    _inherit = "wizard.base.import.pdf.upload.line"

    def _process_form(self):
        """Same contract as the base method, but nothing escapes it
        un-translated except an expected, already-user-facing exception
        (`UserError`/`RedirectWarning`) or a database-transaction error.

        `edi.backend.exchange_process()` only turns an exception into a
        clean `exchange_error` + chatter notification for
        `UserError`/`ValidationError` (see its `_swallable_exceptions()`);
        anything else - notably `odoo.tests.Form`'s own bare
        `AssertionError` for a required field left empty - escapes that
        machinery entirely; a `finally` block still writes back, but the
        exception keeps propagating past the `except`/`else` branches that
        would otherwise set `state`/`error`, so the record isn't even
        marked as errored, only exploded as a raw traceback wherever the
        caller (a manual upload's controller, an EDI job) happens to
        surface it. `_process_child_lines()` below gives the CHILD-line
        case a specific, informative message; this wraps the whole method
        as a safety net for anything else - a less specific message, but
        still a clean one, with the real exception chained via `from err`
        so the full traceback is exactly what `exchange_process()` already
        captures into `exchange_error_traceback` for anyone who needs it.

        A `psycopg2.Error` (a DB-transaction failure - e.g. `IntegrityError`
        from a unique constraint) must NOT be converted: `exchange_process()`
        specifically detects those and skips its own `finally` write-back,
        because the cursor is already in an aborted state and any further
        query - including that write-back - would raise a second, worse
        error ("current transaction is aborted"). Converting it to a
        `UserError` here would hide that from `exchange_process()` and
        trigger exactly that.
        """
        try:
            return super()._process_form()
        except (UserError, exceptions.RedirectWarning, Psycopg2Error):
            raise
        except Exception as err:  # pylint: disable=W8138
            _logger.exception(
                "base_import_pdf_by_template: unexpected error while "
                "processing an import - see the chained traceback."
            )
            raise UserError(self._unexpected_form_error_message(err)) from err

    def _unexpected_form_error_message(self, err: Exception) -> str:
        """A one-line, still-somewhat-generic summary for whatever
        `_process_form()`'s safety net catches that neither
        `_process_child_lines()` nor the base module's own
        `_create_or_update_record()` already gave a specific message -
        the exception's class and text beat a bare stack trace, even
        when nothing more specific was written for it."""
        return self.env._(
            "This document could not be created (%(kind)s: %(message)s).",
            kind=type(err).__name__,
            message=str(err) or repr(err),
        )

    def _required_field_label(self, model_name: str, err: Exception) -> str | None:
        """`None`, or a human sentence for a Form's own required-field
        `AssertionError`/its base-module `UserError` wrapper - resolving
        the bare field name in the Python-internal message to that
        field's actual label, on `model_name` (the record the Form was
        building when it failed)."""
        text = str(err.args[0]) if getattr(err, "args", None) else str(err)
        match = _REQUIRED_FIELD_RE.match(text)
        if not match or model_name not in self.env:
            return None
        field_name = match.group("quoted") or match.group("bare")
        field = self.env[model_name]._fields.get(field_name)
        label = field.string if field else field_name
        return self.env._("'%s' has no value, but it is required", label)

    def _row_summary(self, values: dict) -> str | None:
        """A short, human-readable snippet of `values` (a table row's
        already-resolved field values, as `_process_child_lines()` has
        them) to help identify WHICH row failed - Form's own assertion
        says only which field, and there is no raw text left to quote by
        the time it fails. Record values show their display name; a
        one2many/many2many's own commands are skipped as noise."""
        parts = []
        for field_name, value in values.items():
            if isinstance(value, models.BaseModel):
                if not value:
                    continue
                value = value.display_name
            elif isinstance(value, (list, tuple)):
                continue
            elif value in (False, None, ""):
                continue
            parts.append(f"{field_name}={value}")
            if len(parts) >= 3:
                break
        return ", ".join(parts) if parts else None

    def _child_line_error_hint(self, template, values: dict) -> str | None:
        """Extra guidance appended after a child-line error - nothing in
        this module, since it doesn't know about any particular field
        SOURCE (a bridge module like `import_create_missing` does, and
        extends this)."""
        return None

    def _child_line_error_message(self, template, index: int, values: dict, err) -> str:
        """The full message for a child-line `AssertionError` - the field
        that's missing (by its real label when recognized), which row,
        what that row otherwise resolved to, and any bridge-specific hint
        (e.g. "check Settings > Technical > Logging...")."""
        reason = self._required_field_label(template.child_model, err) or str(err)
        lines = [
            self.env._(
                "Row %(index)s could not be saved: %(reason)s.",
                index=index,
                reason=reason,
            )
        ]
        summary = self._row_summary(values)
        if summary:
            lines.append(self.env._("Row data: %s", summary))
        hint = self._child_line_error_hint(template, values)
        if hint:
            lines.append(hint)
        return "\n".join(lines)

    def _process_child_lines(self, model_form, template, text):
        """Same contract as the base method, but a row whose Form can't be
        saved (typically: a required field on the child model that
        nothing - extraction, a fixed value, `create_missing` - filled in)
        raises a `UserError` naming the row and the field instead of
        letting `odoo.tests.Form`'s bare `AssertionError` escape whole."""
        table_info = template._get_table_info(text)
        lines_values = template._get_field_child_values(table_info)
        for index, line in enumerate(lines_values, start=1):
            child_line = getattr(model_form, template.child_field_name)
            try:
                with child_line.new() as line_form:
                    self._set_child_fixed_values(line_form, template)
                    self._set_child_line_values(line_form, template, line)
            except AssertionError as err:
                raise UserError(
                    self._child_line_error_message(template, index, line, err)
                ) from err

    def _create_or_update_record(self, model_form, model, ctx, extra_vals):
        """Same contract as the base method - which already converts its
        OWN `AssertionError` (the top-level Form's required-field check)
        into a `UserError`, just with the bare Python-internal text. This
        re-words it the same way a child line's is worded, when it
        recognizes the shape; anything else passes through unchanged."""
        try:
            return super()._create_or_update_record(model_form, model, ctx, extra_vals)
        except UserError as err:
            reason = self._required_field_label(model._name, err)
            if reason is None:
                raise
            raise UserError(
                self.env._("This document could not be saved: %s.", reason)
            ) from err

    def _set_header_values(self, model_form, template, text):
        """Same contract as the base method, but sets plain fields before
        computed ones (see `_sorted_extracted_items`)."""
        header_values = template._get_field_header_values(text)
        for field_name, field_data in self._sorted_extracted_items(
            template.model, header_values
        ):
            self.with_context(
                model_name=template.model, related_model="header"
            )._process_set_value_form(model_form, field_name, field_data)

    def _set_child_line_values(self, line_form, template, line):
        """Same contract as the base method, but sets plain fields before
        computed ones (see `_sorted_extracted_items`).
        """
        for field_name, field_value in self._sorted_extracted_items(
            template.child_model, line
        ):
            self.with_context(
                model_name=template.child_model, related_model="lines"
            )._process_set_value_form(line_form, field_name, field_value)

    def _sorted_extracted_items(self, model_name, values):
        """The extracted `(field_name, value)` pairs for one record, ordered
        so that Odoo's own computes cannot undo the template's work.

        `odoo.tests.Form` (used by the base module's `_process_form()`)
        replays the server's onchange/compute machinery on every
        assignment: as soon as a field a stored computed field depends on
        is assigned, that compute re-fires and overwrites whatever was
        already set on the new record - even a value a template line
        extracted earlier. The reported case: a purchase.order.line
        template sets `price_unit` from the email's own "Cost $X /Each"
        line, then `product_qty` - and `purchase.order.line._compute_
        price_unit_and_date_planned_and_name()` (depends: product_qty,
        product_uom, company_id, order_id.partner_id) re-derives
        price_unit from the vendor's product.supplierinfo.price,
        discarding the extracted cost. Reordering the template's own
        lines cannot fix this in general: which assignment fires the
        compute is a property of Odoo's field dependency graph, not of
        the template.

        The ordering property that DOES hold regardless of the graph:
        a compute only re-fires when one of the fields it depends on is
        assigned *after* the value it must not clobber. So plain fields
        go first, then computed (readonly=False, stored) fields, ordered
        so that any field another extracted field's compute depends on is
        assigned first - price_unit, whose compute reads product_qty,
        ends up set after product_qty and is the last word.

        No reordering is needed at create() time: `create()`/`write()`
        treat an explicitly provided value for a stored computed
        readonly=False field as final and never recompute it from the
        vals alone, so the form's final in-memory state is exactly what
        gets stored.
        """
        model = self.env[model_name]
        fields = model._fields

        def is_clobberable(name):
            field = fields.get(name)
            return bool(field and field.compute and field.store and not field.readonly)

        def direct_dependencies(name):
            depends = fields[name].get_depends(model)[0]
            return {d.split(".")[0] for d in depends if d}

        plain = [
            (name, value)
            for name, value in values.items()
            if not is_clobberable(name)
        ]
        remaining = [name for name, _ in values.items() if is_clobberable(name)]
        ordered = list(plain)
        # Kahn-style ordering of the computed group on the *dependency*
        # direction between the extracted fields themselves; anything
        # left in a cycle (no sensible order exists) keeps its original
        # relative order.
        while remaining:
            ready = [
                name
                for name in remaining
                if not (direct_dependencies(name) & set(remaining))
            ]
            if not ready:
                ready = remaining
            for name in ready:
                ordered.append((name, values[name]))
                remaining.remove(name)
        return ordered
