# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import models


class WizardBaseImportPdfUploadLine(models.TransientModel):
    _inherit = "wizard.base.import.pdf.upload.line"

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
