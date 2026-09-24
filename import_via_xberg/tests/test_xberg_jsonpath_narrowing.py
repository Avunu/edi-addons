# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import json

from odoo.addons.base.tests.common import BaseCommon

from odoo.addons.import_via_xberg.models.base_import_pdf_template_line import (
    _unescape_jsonpath_whitespace,
)

# A trimmed-down stand-in for `_add_table_cell_views(_to_jsonable(document))`
# - enough structure to exercise `xberg_jsonpath` narrowing followed by a
# regex `pattern`, for both a single header value and a multi-row column,
# without depending on the real extraction pipeline.
SAMPLE_ENVELOPE = {
    "content": "EXAMPLE TRUCK\nDATE SHIPPED 8/20/2026",
    "tables": [
        {
            "cells": [
                ["QTY SHP", "QTY B/O", "ITEM"],
                ["2", "", "201P/90-0013"],
            ],
            "cellsByHeader": [
                {"ITEM": "201P/90-0013", "Part\n Number": "23151592"},
                {"ITEM": "300X/12-9999"},
            ],
        }
    ],
    "extra": {"lat": "12.50"},
}
SAMPLE_TEXT = json.dumps(SAMPLE_ENVELOPE)


class TestXbergJsonpathNarrowing(BaseCommon):
    """`pattern` is always a plain regex, on every template regardless of
    extraction mode - `xberg_jsonpath` (only meaningful on an `xberg`
    template) is an optional pre-filter: when set, it narrows the document
    down to whatever it selects (one JSONPath match per line) *before*
    `pattern`'s regex searches it, instead of the regex searching the
    whole raw document. These tests exercise that two-stage flow through
    the real `_get_field_value()`/`_get_column_values()` entry points, the
    same ones the base module and `base_import_pdf_by_template_engine`
    already use - no override of pattern application itself is needed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model_id = cls.env.ref("base.model_res_partner").id
        cls.name_field_id = cls.env.ref("base.field_res_partner__name").id
        cls.xberg_template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Xberg Narrowing Template",
                "model_id": cls.partner_model_id,
                "extraction_mode": "xberg",
            }
        )

    def _make_line(self, template=None, **values):
        vals = {
            "template_id": (template or self.xberg_template).id,
            "related_model": "header",
            "field_id": self.name_field_id,
        }
        vals.update(values)
        return self.env["base.import.pdf.template.line"].create(vals)

    def test_header_narrowed_then_refined_by_regex(self):
        # jsonpath selects the whole item code; the regex then pulls just
        # the trailing digits out of it - the "select, then refine" flow
        # this field exists for.
        line = self._make_line(
            xberg_jsonpath="$.tables[0].cells[1][2]", pattern=r"(\d+)$"
        )
        self.assertEqual(line._get_field_value(SAMPLE_TEXT), "0013")

    def test_blank_jsonpath_falls_back_to_whole_document(self):
        # No xberg_jsonpath set -> pattern's regex searches the whole raw
        # JSON document directly, exactly like a non-xberg template.
        line = self._make_line(pattern=r'"lat":\s*"([\d.]+)"')
        self.assertEqual(line._get_field_value(SAMPLE_TEXT), "12.50")

    def test_column_narrowed_to_multiple_rows_then_refined(self):
        line = self._make_line(
            related_model="lines",
            xberg_jsonpath="$.tables[0].cellsByHeader[*].ITEM",
            pattern=r"(\d+)$",
        )
        self.assertEqual(line._get_column_values(SAMPLE_TEXT), ["0013", "9999"])

    def test_process_value_tail_applies_float_conversion_unmodified(self):
        """No override of `_process_value()` exists in this module any
        more - `pattern` is always a real regex, so the base module's own
        post-processing (date/float conversion, mapped_ids, search_field_id)
        just runs normally against whatever `_xberg_narrow_text()` narrowed
        the input down to.
        """
        line = self._make_line(
            field_id=self.env.ref("base.field_res_partner__partner_latitude").id,
            xberg_jsonpath="$.extra.lat",
            pattern="(.+)",
        )
        self.assertEqual(line._get_field_value(SAMPLE_TEXT), 12.5)

    def test_process_value_tail_applies_mapped_ids_unmodified(self):
        title = self.env["res.partner.title"].create({"name": "Narrowing Test Title"})
        line = self._make_line(
            field_id=self.env.ref("base.field_res_partner__title").id,
            xberg_jsonpath="$.tables[0].cells[0][0]",
            pattern="(.+)",
            mapped_ids=[
                (0, 0, {"origin": "QTY SHP", "value": f"res.partner.title,{title.id}"})
            ],
        )
        self.assertEqual(line._get_field_value(SAMPLE_TEXT), title)

    def test_wrapped_header_key_matched_via_escaped_newline(self):
        # A PDF table header that wraps across two lines comes through
        # extraction as a key containing a real newline character (see
        # "Part\n Number" above). A user can't type a literal newline into
        # the xberg_jsonpath Char field, so `\n` typed as two characters
        # (backslash, n) must be understood the same way.
        line = self._make_line(
            xberg_jsonpath="$.tables[0].cellsByHeader[0]['Part\\n Number']",
            pattern="(.+)",
        )
        self.assertEqual(line._get_field_value(SAMPLE_TEXT), "23151592")

    def test_non_xberg_template_ignores_xberg_jsonpath(self):
        # `xberg_jsonpath` is only meaningful on an `xberg` template - on
        # any other mode it must be a complete no-op, not even attempted
        # (the plain-text `text` here isn't valid JSON at all, so trying to
        # evaluate the JSONPath against it would raise).
        pypdf_template = self.env["base.import.pdf.template"].create(
            {
                "name": "Regex-only Template",
                "model_id": self.partner_model_id,
                "extraction_mode": "pypdf",
            }
        )
        line = self._make_line(
            template=pypdf_template,
            xberg_jsonpath="$.should.never.be.evaluated",
            pattern=r"Partner Name: (.+)",
        )
        self.assertEqual(
            line._get_field_value("Partner Name: Acme Corp"), "Acme Corp"
        )


class TestXbergJsonpathPreview(BaseCommon):
    """`xberg_jsonpath_preview` shows what `xberg_jsonpath` currently
    selects from the template's sample document, so a template author can
    see that *before* writing `pattern`'s regex against it - the narrowing
    step made visible on its own, separate from `import_preview`'s
    `preview_result` (the final, regex-refined value).

    `import_preview` is installed for these tests (both modules only
    depend on `base_import_pdf_by_template_engine`, not on each other,
    but installing both together - the way they are actually meant to be
    used - is what makes `template_id.sample_data` exist at all; see
    `_xberg_jsonpath_preview_depends()`'s docstring for how the compute
    stays safe without it).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.name_field_id = cls.env.ref("base.field_res_partner__name").id
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Xberg Preview Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "extraction_mode": "xberg",
            }
        )

    def _make_line(self, **values):
        vals = {
            "template_id": self.template.id,
            "related_model": "header",
            "field_id": self.name_field_id,
        }
        vals.update(values)
        return self.env["base.import.pdf.template.line"].create(vals)

    def test_blank_without_xberg_jsonpath(self):
        self.template.sample_data = SAMPLE_TEXT
        line = self._make_line()
        self.assertFalse(line.xberg_jsonpath_preview)

    def test_placeholder_without_sample_data(self):
        self.template.sample_data = False
        line = self._make_line(xberg_jsonpath="$.content")
        self.assertIn("sample document", line.xberg_jsonpath_preview)

    def test_numbered_matches_with_sample_data(self):
        self.template.sample_data = SAMPLE_TEXT
        line = self._make_line(xberg_jsonpath="$.tables[0].cellsByHeader[*].ITEM")
        preview = line.xberg_jsonpath_preview
        self.assertIn("2 match(es)", preview)
        self.assertIn("1. '201P/90-0013'", preview)
        self.assertIn("2. '300X/12-9999'", preview)

    def test_wrapped_header_key_matched_via_escaped_newline(self):
        self.template.sample_data = SAMPLE_TEXT
        line = self._make_line(
            xberg_jsonpath="$.tables[0].cellsByHeader[0]['Part\\n Number']"
        )
        self.assertIn("'23151592'", line.xberg_jsonpath_preview)

    def test_no_match(self):
        self.template.sample_data = SAMPLE_TEXT
        line = self._make_line(xberg_jsonpath="$.tables[5].cells[0][0]")
        self.assertEqual(line.xberg_jsonpath_preview, "No match.")

    def test_invalid_expression_renders_instead_of_raising(self):
        self.template.sample_data = SAMPLE_TEXT
        line = self._make_line(xberg_jsonpath="$.[[[not valid")
        self.assertTrue(line.xberg_jsonpath_preview.startswith("⚠"))

    def test_blank_on_non_xberg_template(self):
        pypdf_template = self.env["base.import.pdf.template"].create(
            {
                "name": "Regex-only Preview Template",
                "model_id": self.env.ref("base.model_res_partner").id,
                "extraction_mode": "pypdf",
            }
        )
        pypdf_template.sample_data = "Partner Name: Acme Corp"
        line = self.env["base.import.pdf.template.line"].create(
            {
                "template_id": pypdf_template.id,
                "related_model": "header",
                "field_id": self.name_field_id,
                "xberg_jsonpath": "$.content",
            }
        )
        self.assertFalse(line.xberg_jsonpath_preview)


class TestUnescapeJsonpathWhitespace(BaseCommon):
    """`_unescape_jsonpath_whitespace()` in isolation - the helper the
    fields above exercise indirectly through the ORM."""

    def test_newline_tab_and_carriage_return_are_unescaped(self):
        self.assertEqual(
            _unescape_jsonpath_whitespace("['Part\\n Number']"), "['Part\n Number']"
        )
        self.assertEqual(_unescape_jsonpath_whitespace("['A\\tB']"), "['A\tB']")
        self.assertEqual(_unescape_jsonpath_whitespace("['A\\rB']"), "['A\rB']")

    def test_expression_without_escapes_is_unchanged(self):
        expression = "$.tables[0].cellsByHeader[*].ITEM"
        self.assertEqual(_unescape_jsonpath_whitespace(expression), expression)
