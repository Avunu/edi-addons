# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from base64 import b64encode

from odoo.modules.module import get_module_resource
from odoo.tests import Form

from odoo.addons.base.tests.common import BaseCommon


class TestPreview(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.name_field = cls.env.ref("base.field_res_partner__name")
        cls.street_field = cls.env.ref("base.field_res_partner__street")
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Preview Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "sample_data": "Name: Alice\nStreet: Main St\n",
            }
        )

    def _make_line(self, **values):
        vals = {
            "template_id": self.template.id,
            "related_model": "header",
            "field_id": self.name_field.id,
        }
        vals.update(values)
        return self.env["base.import.pdf.template.line"].create(vals)

    def test_no_sample_data_shows_placeholder(self):
        template = self.env["base.import.pdf.template"].create(
            {"name": "Empty", "model_id": self.env.ref("base.model_res_partner").id}
        )
        line = self.env["base.import.pdf.template.line"].create(
            {
                "template_id": template.id,
                "related_model": "header",
                "field_id": self.name_field.id,
                "pattern": "Name: (.*)",
            }
        )
        self.assertIn("sample", line.preview_result.lower())

    def test_no_pattern_shows_placeholder(self):
        line = self._make_line()
        self.assertEqual(line.preview_result, "No pattern set.")

    def test_header_match_shown(self):
        line = self._make_line(pattern="Name: (.*)")
        self.assertIn("Alice", line.preview_result)

    def test_no_match_reported(self):
        line = self._make_line(pattern="Phone: (.*)")
        self.assertEqual(line.preview_result, "No match.")

    def test_invalid_regex_renders_instead_of_raising(self):
        line = self._make_line(pattern="(unclosed")
        self.assertTrue(line.preview_result.startswith("⚠"))

    def test_search_field_no_record_found_is_explicit(self):
        line = self._make_line(
            field_id=self.env.ref("base.field_res_partner__country_id").id,
            pattern="Street: (.*)",
            search_field_id=self.env.ref("base.field_res_country__code").id,
        )
        self.assertIn("No res.country found", line.preview_result)

    def test_column_preview_shows_cardinality_and_processed_value(self):
        template = self.env["base.import.pdf.template"].create(
            {
                "name": "Lines Preview",
                "model_id": self.env.ref("base.model_res_partner").id,
                "sample_data": "Row: A1\nRow: A2\nRow: A3\n",
            }
        )
        line = self.env["base.import.pdf.template.line"].create(
            {
                "template_id": template.id,
                "related_model": "lines",
                "field_id": self.name_field.id,
                "pattern": r"Row: (\w+)",
            }
        )
        self.assertIn("3 value(s)", line.preview_result)
        self.assertIn("A1", line.preview_result)

    def test_preview_updates_from_unsaved_parent_sample_data(self):
        """The load-bearing claim behind the whole module: a non-stored
        compute on an o2m child, depending on a related mirror of the
        *unsaved* parent's `sample_data`, recomputes live inside the line
        dialog `Form()` opens - the same onchange machinery the web client
        uses for the real dialog.
        """
        template_form = Form(self.env["base.import.pdf.template"])
        template_form.name = "Live Preview"
        template_form.model_id = self.env.ref("base.model_res_partner")
        template_form.sample_data = "Name: Bob\n"
        with template_form.line_ids.new() as line_form:
            line_form.related_model = "header"
            line_form.field_id = self.name_field
            line_form.pattern = "Name: (.*)"
            self.assertIn("Bob", line_form.preview_result)

    def test_sample_file_onchange_fills_sample_data(self):
        pdf_path = get_module_resource(
            "base_import_pdf_by_template", "tests", "data", "res-partner.pdf"
        )
        with open(pdf_path, "rb") as f:
            pdf_data = b64encode(f.read())
        template_form = Form(self.env["base.import.pdf.template"])
        template_form.name = "From File"
        template_form.model_id = self.env.ref("base.model_res_partner")
        template_form.sample_file = pdf_data
        self.assertIn("Test partner info", template_form.sample_data)

    def test_preview_summary_renders_header_and_lines(self):
        template = self.env["base.import.pdf.template"].create(
            {
                "name": "Summary Test",
                "model_id": self.env.ref("base.model_res_partner").id,
                "sample_data": "Name: Alice\nRow: A1\nRow: A2\n",
            }
        )
        self.env["base.import.pdf.template.line"].create(
            {
                "template_id": template.id,
                "related_model": "header",
                "field_id": self.name_field.id,
                "pattern": "Name: (.*)",
            }
        )
        self.env["base.import.pdf.template.line"].create(
            {
                "template_id": template.id,
                "related_model": "lines",
                "field_id": self.name_field.id,
                "pattern": r"Row: (\w+)",
            }
        )
        summary = template.preview_summary
        self.assertIn("Alice", summary)
        self.assertIn("Lines (2)", summary)
