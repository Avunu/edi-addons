# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo.tests import tagged
from odoo.addons.base.tests.common import BaseCommon

_TAGS = ("post_install", "-at_install")


@tagged(*_TAGS)
class TestNestedOneToMany(BaseCommon):
    """`create.value._extract_one2many_commands()` - a New Document
    Values row whose Field is a one2many (e.g. a newly-created vendor's
    own bank accounts) gets its rows from `child_value_ids`, each
    extracted fresh from the WHOLE document and paired by match position
    - not tied to the outer line's own row, since there is no
    per-row-relative pattern language to give it just one row's slice.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env["base.import.pdf.template"]
        cls.Line = cls.env["base.import.pdf.template.line"]
        cls.CreateValue = cls.env["base.import.pdf.template.line.create.value"]
        cls.template = cls.Template.create(
            {
                "name": "Nested O2M Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "child_field_id": cls.env.ref(
                    "base.field_res_partner__child_ids"
                ).id,
            }
        )
        # A "header" line: the missing PARENT COMPANY of the imported
        # contact - itself a res.partner, so it can carry its own nested
        # bank_ids, exactly like a newly-created vendor would.
        cls.line = cls.Line.create(
            {
                "template_id": cls.template.id,
                "related_model": "header",
                "field_id": cls.env.ref("base.field_res_partner__parent_id").id,
                "search_field_id": cls.env.ref("base.field_res_partner__name").id,
                "create_missing": True,
                "pattern": r"Vendor: (.+)\n",
            }
        )
        cls.bank_ids_field = cls.env.ref("base.field_res_partner__bank_ids")
        cls.acc_number_field = cls.env.ref(
            "base.field_res_partner_bank__acc_number"
        )

    def _make_bank_create_value(self):
        return self.CreateValue.create(
            {
                "line_id": self.line.id,
                "field_id": self.bank_ids_field.id,
                "value_type": "variable",
            }
        )

    def test_one2many_rows_paired_by_match_position(self):
        bank_row = self._make_bank_create_value()
        self.CreateValue.create(
            {
                "line_id": self.line.id,
                "parent_id": bank_row.id,
                "field_id": self.acc_number_field.id,
                "value_type": "variable",
                "pattern": r"Bank: (\S+)\n",
            }
        )
        text = "Vendor: Acme Corp\nBank: 111-222\nBank: 333-444\n"
        header_values = self.template.with_context(
            import_create_missing=True
        )._get_field_values("header", text)
        parent = header_values.get("parent_id")
        self.assertTrue(parent)
        self.assertEqual(parent.name, "Acme Corp")
        self.assertEqual(sorted(parent.bank_ids.mapped("acc_number")), [
            "111-222",
            "333-444",
        ])

    def test_one2many_with_only_fixed_children_creates_one_row(self):
        bank_row = self._make_bank_create_value()
        self.CreateValue.create(
            {
                "line_id": self.line.id,
                "parent_id": bank_row.id,
                "field_id": self.acc_number_field.id,
                "value_type": "fixed",
                "fixed_value": "000-FIXED",
            }
        )
        text = "Vendor: Fixed Corp\n"
        header_values = self.template.with_context(
            import_create_missing=True
        )._get_field_values("header", text)
        parent = header_values.get("parent_id")
        self.assertTrue(parent)
        self.assertEqual(parent.bank_ids.mapped("acc_number"), ["000-FIXED"])

    def test_ragged_child_columns_skip_the_whole_one2many(self):
        bank_row = self._make_bank_create_value()
        self.CreateValue.create(
            {
                "line_id": self.line.id,
                "parent_id": bank_row.id,
                "field_id": self.acc_number_field.id,
                "value_type": "variable",
                "pattern": r"Bank: (\S+)\n",
            }
        )
        # A second child column with a different match count - one2many
        # extraction can't align them, so no bank rows are created at all
        # (the parent company itself is still created).
        self.CreateValue.create(
            {
                "line_id": self.line.id,
                "parent_id": bank_row.id,
                "field_id": self.env.ref(
                    "base.field_res_partner_bank__sequence"
                ).id,
                "value_type": "variable",
                "pattern": r"ONLY-ONE: (\d+)",
            }
        )
        text = "Vendor: Ragged Corp\nBank: 111-222\nBank: 333-444\nONLY-ONE: 1\n"
        with self.assertLogs(
            "odoo.addons.import_create_missing.models."
            "base_import_pdf_template_line_create_value",
            level="WARNING",
        ):
            header_values = self.template.with_context(
                import_create_missing=True
            )._get_field_values("header", text)
        parent = header_values.get("parent_id")
        self.assertTrue(parent)
        self.assertFalse(parent.bank_ids)

    def test_no_child_values_creates_no_rows(self):
        self._make_bank_create_value()
        text = "Vendor: Bankless Corp\n"
        header_values = self.template.with_context(
            import_create_missing=True
        )._get_field_values("header", text)
        parent = header_values.get("parent_id")
        self.assertTrue(parent)
        self.assertFalse(parent.bank_ids)

    def test_candidate_model_ids_includes_delegated_parent(self):
        # `res.users` delegates to `res.partner` via `_inherits` - a New
        # Document Values row targeting `res.users` should still be able
        # to pick a field that's really defined on `res.partner`.
        user_line = self.Line.create(
            {
                "template_id": self.template.id,
                "related_model": "header",
                "field_id": self.env.ref("base.field_res_partner__user_id").id,
                "search_field_id": self.env.ref("base.field_res_users__login").id,
                "create_missing": True,
                "pattern": r"User: (\S+)\n",
            }
        )
        create_value = self.CreateValue.create(
            {
                "line_id": user_line.id,
                "field_id": self.env.ref("base.field_res_users__login").id,
                "value_type": "fixed",
                "fixed_value": "someone",
            }
        )
        self.assertEqual(create_value.model, "res.users")
        self.assertIn(
            self.env.ref("base.model_res_partner").id,
            create_value.candidate_model_ids.ids,
        )
        self.assertIn(
            self.env.ref("base.model_res_users").id,
            create_value.candidate_model_ids.ids,
        )
