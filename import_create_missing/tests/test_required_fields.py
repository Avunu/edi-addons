# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Auto-population of New Document Values from the target model's own
required fields, the typed `Fixed` values that carry Odoo's defaults, and
the advisory "still missing" reporting built on both."""
from odoo.tests import tagged
from odoo.addons.base.tests.common import BaseCommon

from odoo.addons.import_create_missing.models.create_field_spec import (
    fixed_value_kind,
    required_field_names,
    required_field_specs,
)

# post_install, not at_install - same reason as the sibling suites: this
# module loads before `account` in a full-registry load, and an at_install
# res.partner create() can die on a not-yet-attached ORM default.
_TAGS = ("post_install", "-at_install")


@tagged(*_TAGS)
class TestRequiredFieldSpecs(BaseCommon):
    """`create_field_spec` on its own - what counts as required, and what
    Odoo would default."""

    def test_required_specs_for_res_users(self):
        specs = {spec.name: spec for spec in required_field_specs(self.env["res.users"])}
        # Owned by res.users itself, required, nothing defaults it.
        self.assertIn("login", specs)
        self.assertFalse(specs["login"].has_default)
        # Required AND defaulted - never "missing".
        self.assertIn("company_id", specs)
        self.assertTrue(specs["company_id"].has_default)
        self.assertEqual(specs["company_id"].default, self.env.company.id)
        # The `_inherits` link is required but must never be offered: the
        # very same create() builds the parent from the delegated values.
        self.assertNotIn("partner_id", specs)

    def test_exclude_is_honoured(self):
        names = required_field_names(self.env["res.users"], exclude=("login",))
        self.assertNotIn("login", names)
        self.assertIn("company_id", names)

    def test_computed_and_x2many_required_fields_are_skipped(self):
        names = required_field_names(self.env["res.users"])
        # `display_name` is required-ish but computed; x2many "required"
        # is never enforced on create.
        self.assertNotIn("display_name", names)
        for name in names:
            field = self.env["res.users"]._fields[name].base_field
            self.assertFalse(field.compute, f"{name} is computed")
            self.assertNotIn(field.type, ("one2many", "many2many"))

    def test_fixed_value_kind_mapping(self):
        self.assertEqual(fixed_value_kind("monetary"), "float")
        self.assertEqual(fixed_value_kind("text"), "char")
        self.assertEqual(fixed_value_kind("many2one"), "record")
        # A dynamic selection has no reflected options to offer.
        self.assertEqual(fixed_value_kind("selection", False), "char")
        self.assertEqual(fixed_value_kind("selection", True), "selection")
        self.assertIsNone(fixed_value_kind("one2many"))
        self.assertIsNone(fixed_value_kind(False))


@tagged(*_TAGS)
class TestRequiredCreateValues(BaseCommon):
    """Auto-population, the advisory warning, and typed Fixed values, on
    real template lines."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env["base.import.pdf.template"]
        cls.Line = cls.env["base.import.pdf.template.line"]
        cls.CreateValue = cls.env["base.import.pdf.template.line.create.value"]
        cls.template = cls.Template.create(
            {
                "name": "Required Fields Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "child_field_id": cls.env.ref("base.field_res_partner__child_ids").id,
            }
        )
        # A header line whose linked model is res.users: required fields
        # spread across the model itself (login), a delegated parent
        # (name) and a defaulted many2one (company_id).
        cls.line = cls.Line.create(
            {
                "template_id": cls.template.id,
                "related_model": "header",
                "field_id": cls.env.ref("base.field_res_partner__user_id").id,
                "search_field_id": cls.env.ref("base.field_res_users__login").id,
                "create_missing": True,
                "pattern": r"User: (\S+)\n",
            }
        )
        # The same target model, but searched by a field that is NOT one of
        # its required fields - so `login` stays in play as a required
        # field with no Odoo default, the case the warning is about.
        cls.name_line = cls.Line.create(
            {
                "template_id": cls.template.id,
                "related_model": "header",
                "field_id": cls.env.ref("base.field_res_partner__user_id").id,
                "search_field_id": cls.env.ref("base.field_res_users__name").id,
                "create_missing": True,
                "pattern": r"User: (\S+)\n",
            }
        )

    def _rows(self, line=None):
        line = line if line is not None else self.name_line
        return {
            row.field_name: row
            for row in line.create_value_ids
            if not row.parent_id
        }

    def test_action_adds_required_rows(self):
        self.name_line.action_add_required_create_values()
        rows = self._rows()
        # No Odoo default -> an empty Variable row for the user to fill.
        self.assertIn("login", rows)
        self.assertEqual(rows["login"].value_type, "variable")
        self.assertTrue(rows["login"].is_required)
        # Defaulted -> a Fixed row pre-set to that default, visible and
        # editable rather than invisible.
        self.assertIn("company_id", rows)
        self.assertEqual(rows["company_id"].value_type, "fixed")
        self.assertEqual(rows["company_id"].fixed_value_ref, self.env.company)
        self.assertEqual(rows["company_id"].fixed_value_kind, "record")
        # The `_inherits` link is never offered.
        self.assertNotIn("partner_id", rows)

    def test_search_field_is_not_offered(self):
        # `self.line` searches by login, which `_prepare_create_missing_vals()`
        # already pre-fills with the value that missed - a row for it would
        # just shadow that.
        self.line.action_add_required_create_values()
        rows = self._rows(self.line)
        self.assertNotIn("login", rows)
        self.assertIn("company_id", rows)
        self.assertFalse(self.line.create_missing_warning)

    def test_action_is_idempotent_and_keeps_user_rows(self):
        self.name_line.action_add_required_create_values()
        self._rows()["login"].write({"pattern": r"Login: (.+)\n"})
        before = len(self.name_line.create_value_ids)
        self.name_line.action_add_required_create_values()
        self.assertEqual(len(self.name_line.create_value_ids), before)
        self.assertEqual(self._rows()["login"].pattern, r"Login: (.+)\n")

    def test_onchange_populates_and_drops_stale_rows(self):
        stale = self.CreateValue.create(
            {
                "line_id": self.name_line.id,
                # A res.partner.industry field, on a line that creates a
                # res.users - it can never apply.
                "field_id": self.env.ref(
                    "base.field_res_partner_industry__full_name"
                ).id,
                "value_type": "fixed",
                "fixed_value": "stale",
            }
        )
        self.name_line._onchange_create_missing()
        self.assertNotIn(stale, self.name_line.create_value_ids)
        self.assertIn("login", self._rows())

    def test_warning_lists_unfilled_required_fields(self):
        self.name_line.action_add_required_create_values()
        self.assertIn("Login", self.name_line.create_missing_warning)
        # A defaulted required field is never reported - Odoo fills it.
        self.assertNotIn("Company", self.name_line.create_missing_warning)
        self._rows()["login"].write({"pattern": r"Login: (.+)\n"})
        self.assertFalse(self.name_line.create_missing_warning)

    def test_odoo_default_on_a_field_without_one_is_still_missing(self):
        self.name_line.action_add_required_create_values()
        login_row = self._rows()["login"]
        # `login` is required and Odoo has no default for it.
        login_row.value_type = "odoo_default"
        self.assertFalse(login_row.has_odoo_default)
        self.assertTrue(login_row.has_missing_required)
        self.assertIn("Login", self.name_line.create_missing_warning)

    def test_has_missing_required_per_row(self):
        self.name_line.action_add_required_create_values()
        rows = self._rows()
        self.assertTrue(rows["login"].has_missing_required)
        self.assertFalse(rows["company_id"].has_missing_required)
        rows["login"].write({"pattern": r"Login: (.+)\n"})
        self.assertFalse(rows["login"].has_missing_required)

    def test_nested_row_values_are_prefilled_without_the_inverse(self):
        partner_line = self.Line.create(
            {
                "template_id": self.template.id,
                "related_model": "header",
                "field_id": self.env.ref("base.field_res_partner__parent_id").id,
                "search_field_id": self.env.ref("base.field_res_partner__name").id,
                "create_missing": True,
                "pattern": r"Vendor: (.+)\n",
            }
        )
        bank_row = self.CreateValue.create(
            {
                "line_id": partner_line.id,
                "field_id": self.env.ref("base.field_res_partner__bank_ids").id,
            }
        )
        bank_row._onchange_field_id_children()
        children = {child.field_name for child in bank_row.child_value_ids}
        self.assertIn("acc_number", children)
        # The one2many command sets the inverse itself.
        self.assertNotIn("partner_id", children)
        # A nested row inherits its parent's line even though nothing
        # passed `default_line_id`.
        self.assertEqual(bank_row.child_value_ids.line_id, partner_line)

        self.assertTrue(bank_row.has_missing_required)
        self.assertIn("Account Number", partner_line.create_missing_warning)
        self.assertIn("›", partner_line.create_missing_warning)
        bank_row.child_value_ids.filtered(
            lambda row: row.field_name == "acc_number"
        ).write({"pattern": r"Bank: (\S+)\n"})
        self.assertFalse(bank_row.has_missing_required)

    def test_empty_one2many_reports_nothing(self):
        row = self.CreateValue.create(
            {
                "line_id": self.name_line.id,
                # res.users delegates from res.partner, so its bank
                # accounts are reachable here; res.partner.bank has
                # required fields of its own.
                "field_id": self.env.ref("base.field_res_partner__bank_ids").id,
            }
        )
        # No Row Values -> no sub-record will be created -> its comodel's
        # required fields are not needed yet.
        self.assertFalse(row.has_missing_required)


@tagged(*_TAGS)
class TestTypedFixedValues(BaseCommon):
    """The typed `fixed_value_*` columns and the legacy-value migration."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CreateValue = cls.env["base.import.pdf.template.line.create.value"]
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Typed Values Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "child_field_id": cls.env.ref("base.field_res_partner__child_ids").id,
            }
        )
        cls.line = cls.env["base.import.pdf.template.line"].create(
            {
                "template_id": cls.template.id,
                "related_model": "header",
                "field_id": cls.env.ref("base.field_res_partner__parent_id").id,
                "search_field_id": cls.env.ref("base.field_res_partner__name").id,
                "create_missing": True,
                "pattern": r"Vendor: (.+)\n",
            }
        )

    def _row(self, field_xmlid, **vals):
        return self.CreateValue.create(
            {
                "line_id": self.line.id,
                "field_id": self.env.ref(field_xmlid).id,
                "value_type": "fixed",
                **vals,
            }
        )

    def test_boolean_value_round_trips_false(self):
        row = self._row("base.field_res_partner__is_company", fixed_value_boolean=False)
        self.assertEqual(row.fixed_value_kind, "boolean")
        # A deliberate False is a value, not an omission - it must reach
        # the create-vals rather than being dropped as "empty".
        self.assertIs(row._fixed_create_value(), False)

    def test_integer_value(self):
        row = self._row("base.field_res_partner__color", fixed_value_integer=7)
        self.assertEqual(row.fixed_value_kind, "integer")
        self.assertEqual(row._fixed_create_value(), 7)

    def test_selection_value_returns_the_key(self):
        option = self.env["ir.model.fields.selection"].search(
            [
                ("field_id", "=", self.env.ref("base.field_res_partner__type").id),
                ("value", "=", "invoice"),
            ],
            limit=1,
        )
        self.assertTrue(option)
        row = self._row(
            "base.field_res_partner__type", fixed_value_selection_id=option.id
        )
        self.assertEqual(row.fixed_value_kind, "selection")
        self.assertEqual(row._fixed_create_value(), "invoice")

    def test_char_value_and_empty_is_none(self):
        row = self._row("base.field_res_partner__ref", fixed_value="ABC")
        self.assertEqual(row.fixed_value_kind, "char")
        self.assertEqual(row._fixed_create_value(), "ABC")
        row.fixed_value = False
        self.assertIsNone(row._fixed_create_value())

    def test_odoo_default_contributes_nothing(self):
        # `res.partner.type` really does default (to 'contact').
        row = self._row("base.field_res_partner__type")
        row.value_type = "odoo_default"
        self.assertTrue(row.has_odoo_default)
        # Leaving the key out IS how Odoo's own default gets applied.
        self.assertIsNone(row._to_create_value(None))
        # ...and it counts as handled, not as a missing value.
        self.assertTrue(row._has_value())
        self.assertEqual(row.value_summary, "Odoo default")

    def test_odoo_default_without_a_default_is_not_a_value(self):
        """The one combination that silently guarantees a failed create:
        deferring to a default Odoo does not have. It must NOT count as
        handled, or it would suppress the very warning that says so."""
        row = self._row("base.field_res_partner__ref")
        row.value_type = "odoo_default"
        self.assertFalse(row.has_odoo_default)
        self.assertFalse(row._has_value())
        self.assertIn("no default", row.value_summary)

    def test_legacy_fixed_values_are_migrated(self):
        boolean_row = self._row(
            "base.field_res_partner__is_company", fixed_value="true"
        )
        integer_row = self._row("base.field_res_partner__color", fixed_value="7")
        selection_row = self._row(
            "base.field_res_partner__type", fixed_value="invoice"
        )
        char_row = self._row("base.field_res_partner__ref", fixed_value="ABC")
        self.CreateValue._migrate_legacy_fixed_value()
        self.assertTrue(boolean_row.fixed_value_boolean)
        self.assertFalse(boolean_row.fixed_value)
        self.assertEqual(integer_row.fixed_value_integer, 7)
        self.assertFalse(integer_row.fixed_value)
        self.assertEqual(selection_row.fixed_value_selection_id.value, "invoice")
        self.assertFalse(selection_row.fixed_value)
        # A genuine Char field is left exactly as it was.
        self.assertEqual(char_row.fixed_value, "ABC")

    def test_unparseable_legacy_value_is_left_alone(self):
        row = self._row("base.field_res_partner__color", fixed_value="not a number")
        with self.assertLogs(
            "odoo.addons.import_create_missing.models."
            "base_import_pdf_template_line_create_value",
            level="WARNING",
        ):
            self.CreateValue._migrate_legacy_fixed_value()
        self.assertEqual(row.fixed_value, "not a number")
        self.assertFalse(row.fixed_value_integer)


@tagged(*_TAGS)
class TestProductRequiredFields(BaseCommon):
    """The case this was built for - a product created on the fly needs
    fields from `product.template` as well as its own."""

    def test_product_required_fields(self):
        if "product.product" not in self.env:
            self.skipTest("product is not installed")
        specs = {
            spec.name: spec for spec in required_field_specs(self.env["product.product"])
        }
        # Delegated from product.template, no default - the one field the
        # user genuinely has to map.
        self.assertIn("name", specs)
        self.assertFalse(specs["name"].has_default)
        # `name` is really product.template's - a row's `field_id` domain
        # (candidate_model_ids) only accepts the DEFINING model's record.
        self.assertEqual(
            specs["name"].field_id,
            self.env.ref("product.field_product_template__name").id,
        )
        # Defaulted, so pre-set rather than demanded.
        for name in ("type", "categ_id", "uom_id"):
            self.assertIn(name, specs)
            self.assertTrue(specs[name].has_default, f"{name} should have a default")
        # The delegation link, a computed required field, and a required
        # one2many are all excluded.
        self.assertNotIn("product_tmpl_id", specs)
        self.assertNotIn("uom_po_id", specs)
        self.assertNotIn("product_variant_ids", specs)

    def test_supplierinfo_required_fields_without_inverse(self):
        if "product.supplierinfo" not in self.env:
            self.skipTest("product is not installed")
        names = required_field_names(
            self.env["product.supplierinfo"], exclude=("product_tmpl_id",)
        )
        self.assertIn("partner_id", names)
        self.assertIn("price", names)
        self.assertNotIn("product_tmpl_id", names)

    def test_zero_default_is_a_default(self):
        if "product.supplierinfo" not in self.env:
            self.skipTest("product is not installed")
        specs = {
            spec.name: spec
            for spec in required_field_specs(self.env["product.supplierinfo"])
        }
        # `price`/`min_qty` are required and default to 0.0 - a real
        # default Odoo will apply, not an absent one, so the user is never
        # nagged about them.
        self.assertTrue(specs["price"].has_default)
        self.assertTrue(specs["min_qty"].has_default)
        # ...while a required many2one with no default still is missing.
        self.assertFalse(specs["partner_id"].has_default)
