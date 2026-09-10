# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import re

# post_install, not at_install: this module loads *before* `account` in a
# full-registry load (it only depends on base_import_pdf_by_template), and
# on a database where `account` is installed, res_partner.autopost_bills is
# a NOT NULL column whose ORM default isn't attached yet mid-load - so any
# at_install test creating a res.partner (via BaseCommon's setUpClass) dies
# with a NotNullViolation before this module's own code even runs. After the
# full load the field and its default exist and create works normally - the
# same convention product_napaonline_lookup's own tests use.
from odoo.tests import tagged
from odoo.addons.base.tests.common import BaseCommon


def _original_get_table_info_data(template, text):
    """A frozen copy of `base.import.pdf.template._get_table_info_data()` as
    it exists upstream (pre-refactor), kept here only as a regression
    reference so the refactored implementation can be proven behaviour
    preserving for every non-degenerate input (at least one child line has
    at least one match).
    """
    data = []
    data_map_column = {}
    child_lines = template.line_ids.filtered(
        lambda x: x.related_model == "lines" and x.value_type != "fixed" and x.pattern
    )
    sequence = 0
    for child_line in child_lines:
        data_column = []
        matches = re.finditer(child_line.pattern, text, re.MULTILINE)
        for _matchNum, match in enumerate(matches, start=1):
            match_group = match.groups(0)[0]
            data_column.append(match_group.strip())
        data_map_column[sequence] = data_column
        sequence += 1
    data_keys = list(data_map_column.keys())
    data_key_0 = data_keys[0]
    for x in range(len(data_map_column[data_key_0])):
        line_data = []
        for data_key in data_keys:
            total_items = len(data_map_column[data_key]) - 1
            if total_items >= x:
                line_data.append(data_map_column[data_key][x])
        data.append(line_data)
    return data


@tagged("post_install", "-at_install")
class TestTableInfoData(BaseCommon):
    """`_get_table_info_data()` was refactored to delegate each column to
    `line._get_column_values()` (see `models/base_import_pdf_template.py`)
    so a module can override extraction per line instead of the whole
    table. These tests prove that refactor is behaviour preserving.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_field = cls.env.ref("base.field_res_partner__name")
        cls.model_id = cls.env.ref("base.model_res_partner").id

    def _make_template(self, patterns):
        template = self.env["base.import.pdf.template"].create(
            {"name": "Engine Test Template", "model_id": self.model_id}
        )
        for sequence, pattern in enumerate(patterns):
            self.env["base.import.pdf.template.line"].create(
                {
                    "template_id": template.id,
                    "related_model": "lines",
                    "field_id": self.model_field.id,
                    "pattern": pattern,
                    "sequence": sequence,
                }
            )
        return template

    def test_matches_original_algorithm_even_columns(self):
        text = "Row: A1, B1\nRow: A2, B2\nRow: A3, B3\n"
        template = self._make_template([r"Row: (\w+)", r", (\w+)"])
        self.assertEqual(
            template._get_table_info_data(text),
            _original_get_table_info_data(template, text),
        )

    def test_uneven_columns_are_padded_not_shifted(self):
        # The second pattern only matches twice - the third row's second
        # column is missing. This is a deliberate behaviour *change* from
        # the original algorithm, not an equivalence: the original appends
        # nothing for the missing cell (`data`: [["A1","B1"],["A2","B2"],
        # ["A3"]]), which silently shifts every later column of that row by
        # one when `_get_field_values_from_table_item()` maps cells onto
        # child lines by position. Padding with "" keeps row 3's remaining
        # columns aligned with the right field.
        text = "Row: A1, B1\nRow: A2, B2\nRow: A3\n"
        template = self._make_template([r"Row: (\w+)", r", (\w+)"])
        original = _original_get_table_info_data(template, text)
        self.assertEqual(original, [["A1", "B1"], ["A2", "B2"], ["A3"]])
        self.assertEqual(
            template._get_table_info_data(text),
            [["A1", "B1"], ["A2", "B2"], ["A3", ""]],
        )

    def test_no_patterned_lines_returns_empty_list(self):
        # The original algorithm raises IndexError here (`data_keys[0]` on
        # an empty dict); the refactor must not.
        template = self._make_template([])
        self.assertEqual(template._get_table_info_data("anything"), [])

    def test_pattern_without_capturing_group_falls_back_to_full_match(self):
        # `match.groups(0)[0]` raises IndexError for a pattern with no
        # capturing group at all; the refactored `_get_column_values()`
        # falls back to the whole match instead of crashing.
        text = "AAA\nBBB\nCCC\n"
        template = self._make_template([r"[A-Z]+"])
        self.assertEqual(
            template._get_table_info_data(text), [["AAA"], ["BBB"], ["CCC"]]
        )
