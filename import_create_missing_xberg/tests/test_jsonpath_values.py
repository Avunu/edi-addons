# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import json

from odoo.tests import tagged
from odoo.addons.base.tests.common import BaseCommon

_TAGS = ("post_install", "-at_install")

#: A hand-built stand-in for what `import_via_xberg`'s own extraction
#: (`_add_table_cell_views()`/`_transpose_table_cells()`) would have
#: produced from a real document - built by hand here rather than run
#: through a real extraction, since these tests are only about how
#: `create.value._extract_column()` reads `cellsByHeader`, not about
#: `xberg` itself (that's `import_via_xberg`'s own test suite). One row
#: has a blank Description, one has an embedded newline - both must stay
#: at their own position, never shifting a neighbour.
_SAMPLE_DOCUMENT = {
    "tables": [
        {
            "cellsByHeader": [
                {"Name": "Oak", "Description": "Great oak wood"},
                {"Name": "Pine", "Description": ""},
                {"Name": "Ash", "Description": "Line1\nLine2"},
            ]
        }
    ]
}


@tagged(*_TAGS)
class TestJsonpathValues(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Create Missing Xberg Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "child_field_id": cls.env.ref(
                    "base.field_res_partner__child_ids"
                ).id,
                "extraction_mode": "xberg",
            }
        )
        cls.line = cls.env["base.import.pdf.template.line"].create(
            {
                "template_id": cls.template.id,
                "related_model": "lines",
                "field_id": cls.env.ref(
                    "base.field_res_partner__industry_id"
                ).id,
                "search_field_id": cls.env.ref(
                    "base.field_res_partner_industry__name"
                ).id,
                "create_missing": True,
                "xberg_jsonpath": "$.tables[0].cellsByHeader[*].Name",
                "pattern": "(.+)",
            }
        )
        cls.full_name_field = cls.env.ref(
            "base.field_res_partner_industry__full_name"
        )
        cls.text = json.dumps(_SAMPLE_DOCUMENT)

    def _make_create_value(self, **kwargs):
        vals = {
            "line_id": self.line.id,
            "field_id": self.full_name_field.id,
            "value_type": "variable",
        }
        vals.update(kwargs)
        return self.env["base.import.pdf.template.line.create.value"].create(vals)

    def test_line_itself_finds_three_rows(self):
        # Sanity check on the fixture/line setup: the line's own JSONPath
        # + Pattern combination (import_via_xberg) finds three rows.
        self.assertEqual(
            self.line._get_column_values(self.text), ["Oak", "Pine", "Ash"]
        )

    def test_jsonpath_without_pattern_one_value_per_match(self):
        create_value = self._make_create_value(
            xberg_jsonpath="$.tables[0].cellsByHeader[*].Description"
        )
        self.assertEqual(
            create_value._extract_column(self.text),
            ["Great oak wood", "", "Line1\nLine2"],
        )

    def test_blank_match_does_not_shift_later_rows(self):
        create_value = self._make_create_value(
            xberg_jsonpath="$.tables[0].cellsByHeader[*].Description"
        )
        values = create_value._extract_column(self.text)
        # Row 2 (Pine) has a genuinely blank Description; row 3 (Ash)
        # must still land on ITS OWN value, not row 2's.
        self.assertEqual(values[1], "")
        self.assertEqual(values[2], "Line1\nLine2")

    def test_jsonpath_with_pattern_refines_each_match(self):
        create_value = self._make_create_value(
            xberg_jsonpath="$.tables[0].cellsByHeader[*].Description",
            pattern=r"^(\w+)",
        )
        self.assertEqual(
            create_value._extract_column(self.text),
            ["Great", "", "Line1"],
        )

    def test_end_to_end_creates_missing_industry_with_full_name(self):
        self._make_create_value(
            xberg_jsonpath="$.tables[0].cellsByHeader[*].Description"
        )
        table_info = self.template.with_context(
            import_create_missing=True
        )._get_table_info(self.text)
        self.template.with_context(
            import_create_missing=True
        )._get_field_child_values(table_info)
        oak = self.env["res.partner.industry"].search([("name", "=", "Oak")])
        self.assertTrue(oak)
        self.assertEqual(oak.full_name, "Great oak wood")
        pine = self.env["res.partner.industry"].search([("name", "=", "Pine")])
        self.assertTrue(pine)
        self.assertFalse(pine.full_name)
