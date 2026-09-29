# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from unittest import mock

from odoo.tests import tagged
from odoo.addons.base.tests.common import BaseCommon

# post_install, not at_install - see the identical convention (and full
# explanation) in base_import_pdf_by_template_engine's own tests: this
# module loads before `account` in a full-registry load, and an
# at_install res.partner create() can die on a not-yet-attached ORM
# default for a column `account` adds.
_TAGS = ("post_install", "-at_install")


@tagged(*_TAGS)
class TestCreateMissing(BaseCommon):
    """Exercises `create_missing`/`create_value_ids` directly against the
    template/line methods that actually apply them
    (`_get_table_info`/`_get_field_child_values`/`_get_field_values`,
    `_get_record_search_from_value`) - the same methods a real import
    (`wizard.base.import.pdf.upload.line._process_form()`) drives, without
    needing a real PDF/attachment fixture to get there.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `_log_create_missing()` writes on its OWN cursor, so a log entry
        # survives a failed import's rollback. Test mode turns that cursor
        # into one on this test's transaction, so the entries can be
        # asserted on here and are rolled back with everything else.
        cls.registry.enter_test_mode(cls.cr)
        cls.addClassCleanup(cls.registry.leave_test_mode)
        cls.Template = cls.env["base.import.pdf.template"]
        cls.Line = cls.env["base.import.pdf.template.line"]
        cls.CreateValue = cls.env["base.import.pdf.template.line.create.value"]
        cls.Industry = cls.env["res.partner.industry"]
        cls.template = cls.Template.create(
            {
                "name": "Create Missing Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "child_field_id": cls.env.ref(
                    "base.field_res_partner__child_ids"
                ).id,
            }
        )
        cls.industry_field = cls.env.ref("base.field_res_partner__industry_id")
        cls.industry_name_field = cls.env.ref(
            "base.field_res_partner_industry__name"
        )
        cls.industry_full_name_field = cls.env.ref(
            "base.field_res_partner_industry__full_name"
        )

    def _make_line(self, **kwargs):
        vals = {
            "template_id": self.template.id,
            "related_model": "lines",
            "field_id": self.industry_field.id,
            "search_field_id": self.industry_name_field.id,
            "create_missing": True,
        }
        vals.update(kwargs)
        return self.Line.create(vals)

    def test_variable_value_creates_and_fills_row(self):
        line = self._make_line(pattern=r"Row: (\w+),")
        self.CreateValue.create(
            {
                "line_id": line.id,
                "field_id": self.industry_full_name_field.id,
                "value_type": "variable",
                "pattern": r", (\w+)$",
            }
        )
        text = "Row: Woodworking, WoodworkingFull\nRow: Metalwork, MetalworkFull\n"
        table_info = self.template.with_context(
            import_create_missing=True
        )._get_table_info(text)
        rows = self.template.with_context(
            import_create_missing=True
        )._get_field_child_values(table_info)
        self.assertEqual(len(rows), 2)

        industry = self.Industry.search([("name", "=", "Woodworking")])
        self.assertTrue(industry)
        self.assertEqual(industry.full_name, "WoodworkingFull")
        other = self.Industry.search([("name", "=", "Metalwork")])
        self.assertTrue(other)
        self.assertEqual(other.full_name, "MetalworkFull")

    def test_fixed_value_applied(self):
        line = self._make_line(pattern=r"Row: (\w+)\n")
        self.CreateValue.create(
            {
                "line_id": line.id,
                "field_id": self.industry_full_name_field.id,
                "value_type": "fixed",
                "fixed_value": "Always This",
            }
        )
        text = "Row: Ceramics\n"
        table_info = self.template.with_context(
            import_create_missing=True
        )._get_table_info(text)
        self.template.with_context(
            import_create_missing=True
        )._get_field_child_values(table_info)
        industry = self.Industry.search([("name", "=", "Ceramics")])
        self.assertTrue(industry)
        self.assertEqual(industry.full_name, "Always This")

    def test_repeated_value_creates_once(self):
        line = self._make_line(pattern=r"Row: (\w+)\n")
        text = "Row: Glassblowing\nRow: Glassblowing\n"
        before = self.Industry.search_count([("name", "=", "Glassblowing")])
        table_info = self.template.with_context(
            import_create_missing=True
        )._get_table_info(text)
        self.template.with_context(
            import_create_missing=True
        )._get_field_child_values(table_info)
        after = self.Industry.search_count([("name", "=", "Glassblowing")])
        self.assertEqual(after - before, 1)

    def test_ragged_create_value_column_skips_creation(self):
        line = self._make_line(pattern=r"Row: (\w+),")
        self.CreateValue.create(
            {
                "line_id": line.id,
                "field_id": self.industry_full_name_field.id,
                "value_type": "variable",
                # Only matches once against a two-row document.
                "pattern": r"^ONLY-ONE: (\w+)$",
            }
        )
        text = "Row: Papermaking, x\nRow: Bookbinding, y\nONLY-ONE: solo\n"
        with self.assertLogs(
            "odoo.addons.import_create_missing.models.base_import_pdf_template_line",
            level="WARNING",
        ):
            table_info = self.template.with_context(
                import_create_missing=True
            )._get_table_info(text)
            self.template.with_context(
                import_create_missing=True
            )._get_field_child_values(table_info)
        self.assertFalse(self.Industry.search([("name", "=", "Papermaking")]))
        self.assertFalse(self.Industry.search([("name", "=", "Bookbinding")]))
        # ...and says why, where it can be found (Settings > Technical >
        # Logging) - not only in a server log nobody may be able to read.
        self.assertTrue(self._logged("skipping document creation"))

    def _logged(self, fragment):
        return self.env["ir.logging"].search(
            [("path", "=", "import_create_missing"), ("message", "ilike", fragment)]
        )

    def test_longer_other_column_does_not_block_creation(self):
        """Alignment is checked against the line's OWN column, not the
        whole table. The table is `zip_longest` over every "lines" line, so
        one longer column elsewhere used to make every New Document Values
        column look misaligned - and silently blocked all creation."""
        line = self._make_line(pattern=r"Row: (\w+),")
        self.CreateValue.create(
            {
                "line_id": line.id,
                "field_id": self.industry_full_name_field.id,
                "value_type": "variable",
                "pattern": r", (\w+)$",
            }
        )
        # A second "lines" line whose column is longer than the first's.
        self.Line.create(
            {
                "template_id": self.template.id,
                "related_model": "lines",
                "field_id": self.env.ref("base.field_res_partner__ref").id,
                "pattern": r"^(Ref \w)$",
            }
        )
        text = "Row: Weaving, WeavingFull\nRef A\nRef B\n"
        table_info = self.template.with_context(
            import_create_missing=True
        )._get_table_info(text)
        self.assertEqual(len(table_info["data"]), 2)
        self.template.with_context(
            import_create_missing=True
        )._get_field_child_values(table_info)
        industry = self.Industry.search([("name", "=", "Weaving")])
        self.assertTrue(industry)
        self.assertEqual(industry.full_name, "WeavingFull")

    def test_no_creation_outside_a_real_import(self):
        line = self._make_line(pattern=r"Row: (\w+)\n")
        text = "Row: Leatherworking\n"
        # No `import_create_missing` context flag - same as a template
        # preview or the preview wizard.
        table_info = self.template._get_table_info(text)
        self.template._get_field_child_values(table_info)
        self.assertFalse(self.Industry.search([("name", "=", "Leatherworking")]))

    def test_create_missing_off_is_inert(self):
        line = self._make_line(pattern=r"Row: (\w+)\n", create_missing=False)
        text = "Row: Blacksmithing\n"
        table_info = self.template.with_context(
            import_create_missing=True
        )._get_table_info(text)
        self.template.with_context(
            import_create_missing=True
        )._get_field_child_values(table_info)
        self.assertFalse(self.Industry.search([("name", "=", "Blacksmithing")]))

    def test_header_line_creates_missing_record(self):
        line = self.Line.create(
            {
                "template_id": self.template.id,
                "related_model": "header",
                "field_id": self.industry_field.id,
                "search_field_id": self.industry_name_field.id,
                "create_missing": True,
                "pattern": r"Industry: (\w+)\n",
            }
        )
        self.CreateValue.create(
            {
                "line_id": line.id,
                "field_id": self.industry_full_name_field.id,
                "value_type": "variable",
                "pattern": r"Full: (\w+)\n",
            }
        )
        text = "Industry: Upholstery\nFull: UpholsteryFull\n"
        header_values = self.template.with_context(
            import_create_missing=True
        )._get_field_values("header", text)
        self.assertIn("industry_id", header_values)
        industry = self.Industry.search([("name", "=", "Upholstery")])
        self.assertTrue(industry)
        self.assertEqual(industry.full_name, "UpholsteryFull")
        self.assertEqual(header_values["industry_id"], industry)

    def test_create_failure_falls_through_without_raising(self):
        line = self._make_line(pattern=r"Row: (\w+)\n")
        # `_get_record_search_from_value()` is the method
        # `_prepare_create_missing_vals()`/`create()` actually run inside;
        # call it directly (with the same context shape a real row's
        # extraction would produce) rather than manufacturing a field that
        # genuinely fails `create()` at the ORM layer.
        with mock.patch.object(
            type(self.Industry), "create", side_effect=ValueError("boom")
        ):
            record = line.with_context(
                import_create_missing_values={line.id: {}}
            )._get_record_search_from_value("Papercraft")
        self.assertFalse(record)
        self.assertFalse(self.Industry.search([("name", "=", "Papercraft")]))
        # The reason reaches Settings > Technical > Logging, with the error.
        self.assertTrue(self._logged("failed to create a missing"))
        self.assertTrue(self._logged("boom"))
