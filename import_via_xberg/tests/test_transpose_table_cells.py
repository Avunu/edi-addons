# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo.tests.common import BaseCase

from odoo.addons.import_via_xberg.wizards.wizard_base_import_pdf_mixin import (
    _add_table_cell_views,
    _transpose_table_cells,
)


class TestTransposeTableCells(BaseCase):
    """`BaseCase`, not plain `unittest.TestCase` - see the comment on
    `TestToJsonable` in test_to_jsonable.py: a plain `TestCase` under
    `odoo.addons.*` is silently never collected once `--test-tags`
    filtering is active."""

    def test_header_row_and_data_rows_split_correctly(self):
        cells = [
            ["Item", "Qty", "Price"],
            ["Widget", "2", "10.00"],
            ["Gadget", "1", "5.00"],
        ]
        by_header, by_index = _transpose_table_cells(cells)
        self.assertEqual(
            by_header,
            [
                {"Item": "Widget", "Qty": "2", "Price": "10.00"},
                {"Item": "Gadget", "Qty": "1", "Price": "5.00"},
            ],
        )
        self.assertEqual(
            by_index,
            [
                {"0": "Widget", "1": "2", "2": "10.00"},
                {"0": "Gadget", "1": "1", "2": "5.00"},
            ],
        )

    def test_blank_header_column_omitted_from_by_header_kept_in_by_index(self):
        # An image-only column: header cell blank, data cells still real.
        cells = [
            ["", "Item", "Qty"],
            ["![img](x)", "Widget", "2"],
        ]
        by_header, by_index = _transpose_table_cells(cells)
        self.assertEqual(by_header, [{"Item": "Widget", "Qty": "2"}])
        self.assertEqual(by_index, [{"0": "![img](x)", "1": "Widget", "2": "2"}])

    def test_duplicate_header_last_column_wins_in_by_header(self):
        cells = [
            ["Amount", "Amount"],
            ["10.00", "20.00"],
        ]
        by_header, by_index = _transpose_table_cells(cells)
        self.assertEqual(by_header, [{"Amount": "20.00"}])
        # cellsByIndex is immune to the collision - both values reachable
        self.assertEqual(by_index, [{"0": "10.00", "1": "20.00"}])

    def test_data_row_shorter_than_header_row(self):
        cells = [
            ["Item", "Qty", "Price"],
            ["Widget", "2"],  # missing the Price cell entirely
        ]
        by_header, by_index = _transpose_table_cells(cells)
        self.assertEqual(by_header, [{"Item": "Widget", "Qty": "2"}])
        self.assertEqual(by_index, [{"0": "Widget", "1": "2"}])

    def test_data_row_longer_than_header_row(self):
        cells = [
            ["Item", "Qty"],
            ["Widget", "2", "unexpected extra cell"],
        ]
        by_header, by_index = _transpose_table_cells(cells)
        # no header for column 2, so it cannot appear in cellsByHeader...
        self.assertEqual(by_header, [{"Item": "Widget", "Qty": "2"}])
        # ...but it is not lost - cellsByIndex still has it
        self.assertEqual(
            by_index, [{"0": "Widget", "1": "2", "2": "unexpected extra cell"}]
        )

    def test_empty_table(self):
        self.assertEqual(_transpose_table_cells([]), ([], []))

    def test_header_only_table_has_no_data_rows(self):
        # A single-row table: nothing to transpose into either view (the
        # raw `cells` - untouched by this function - is still the only
        # sane way to read it, which is exactly why callers add these
        # views alongside `cells` rather than replacing it).
        self.assertEqual(_transpose_table_cells([["Order #:", "Y000000001:01"]]), ([], []))

    def test_add_table_cell_views_augments_without_removing_cells(self):
        document = {
            "tables": [
                {"cells": [["Item", "Qty"], ["Widget", "2"]], "page_number": 0},
                # A single-pair label/value table: cells[1:] is empty, so
                # both views come back empty too - nothing to corrupt.
                {"cells": [["Order #:", "Y1"]], "page_number": 1},
                # A *multi*-pair label/value table, though, mechanically
                # looks exactly like a 1-row header + 1 data row to
                # _transpose_table_cells() - it has no way to tell this
                # apart from a real header+data table, so cellsByHeader
                # comes back genuinely nonsensical here (the first pair's
                # *values* become header keys for the second pair). This
                # is the documented tradeoff of not guessing: `cells`
                # stays untouched and correct regardless, which is the
                # actual guarantee this test exists to pin down.
                {"cells": [["Order #:", "Y1"], ["Dealer:", "H510"]], "page_number": 2},
            ]
        }
        result = _add_table_cell_views(document)

        self.assertEqual(
            result["tables"][0]["cells"], [["Item", "Qty"], ["Widget", "2"]]
        )
        self.assertEqual(result["tables"][0]["cellsByHeader"], [{"Item": "Widget", "Qty": "2"}])
        self.assertEqual(result["tables"][0]["cellsByIndex"], [{"0": "Widget", "1": "2"}])

        self.assertEqual(result["tables"][1]["cells"], [["Order #:", "Y1"]])
        self.assertEqual(result["tables"][1]["cellsByHeader"], [])
        self.assertEqual(result["tables"][1]["cellsByIndex"], [])

        self.assertEqual(
            result["tables"][2]["cells"], [["Order #:", "Y1"], ["Dealer:", "H510"]]
        )
        self.assertEqual(result["tables"][2]["cellsByHeader"], [{"Order #:": "Dealer:", "Y1": "H510"}])

    def test_add_table_cell_views_handles_no_tables(self):
        self.assertEqual(_add_table_cell_views({}), {})
        self.assertEqual(_add_table_cell_views({"tables": None}), {"tables": None})
