# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""`_sorted_extracted_items()` ordering - Odoo's own computes must not
undo the template's extracted values.

This reproduces a real production import: a purchase.order template whose
"lines" set `price_unit` from the email's own "Cost $99.99 /Each" line
*before* `product_qty`. `odoo.tests.Form` replays the compute machinery on
every assignment, and `purchase.order.line._compute_price_unit_and_date_
planned_and_name()` (depends: product_qty, product_uom, company_id,
order_id.partner_id) re-derives price_unit from the vendor's
product.supplierinfo.price the moment product_qty is assigned - discarding
the extracted cost and storing 0.0 (that vendor price used to be 0.0 too,
before product_napaonline_lookup started populating it). Reordering the
template's own lines cannot fix this in general; the wizard must.
"""
from unittest import SkipTest

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestExtractedValueOrdering(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            cls.env["purchase.order"]
        except KeyError:
            raise SkipTest("purchase is not installed") from None
        cls.vendor = cls.env["res.partner"].create({"name": "ENGINE TEST VENDOR"})
        cls.product = cls.env["product.product"].create(
            {"name": "Test Part", "default_code": "ENGINE-TEST-1"}
        )
        ref = cls.env.ref
        template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Engine Ordering Test Template",
                "model_id": ref("purchase.model_purchase_order").id,
                "child_field_id": ref("purchase.field_purchase_order__order_line").id,
            }
        )
        template.line_ids = [
            (
                0,
                0,
                {
                    "sequence": 10,
                    "related_model": "header",
                    "field_id": ref("purchase.field_purchase_order__partner_id").id,
                    "pattern": "Vendor: (.*)",
                    "search_field_id": ref("base.field_res_partner__name").id,
                },
            ),
            (
                0,
                0,
                {
                    "sequence": 11,
                    "related_model": "header",
                    "field_id": ref("purchase.field_purchase_order__partner_ref").id,
                    "pattern": "Order #: (.*)",
                },
            ),
            (
                0,
                0,
                {
                    "sequence": 12,
                    "related_model": "lines",
                    "field_id": ref(
                        "purchase.field_purchase_order_line__product_id"
                    ).id,
                    "pattern": r"^ACME ([\w-]+)$",
                    "search_field_id": ref("product.field_product_product__default_code").id,
                },
            ),
            # Deliberately in the order that used to lose: price_unit is
            # extracted BEFORE product_qty, so product_qty's assignment used
            # to fire the price compute afterwards and clobber it.
            (
                0,
                0,
                {
                    "sequence": 13,
                    "related_model": "lines",
                    "field_id": ref(
                        "purchase.field_purchase_order_line__price_unit"
                    ).id,
                    "pattern": r"Cost \$([\d.]+) /Each",
                },
            ),
            (
                0,
                0,
                {
                    "sequence": 14,
                    "related_model": "lines",
                    "field_id": ref(
                        "purchase.field_purchase_order_line__product_qty"
                    ).id,
                    "pattern": "Qty/Car (\\d+)",
                },
            ),
        ]
        cls.template = template
        cls.data = "\n".join(
            [
                "Order #: NPPLK-ENGINE-TEST",
                "Vendor: ENGINE TEST VENDOR",
                "ACME ENGINE-TEST-1",
                "Cost $99.99 /Each",
                "Qty/Car 2",
                "",
            ]
        )

    def _process(self):
        line = self.env["wizard.base.import.pdf.upload.line"].create({})
        line.template_id = self.template.id
        line.data = self.data
        return line._process_form()

    def test_extracted_price_survives_the_product_qty_compute(self):
        record = self._process()
        self.assertEqual(record.partner_ref, "NPPLK-ENGINE-TEST")
        self.assertEqual(len(record.order_line), 1)
        order_line = record.order_line
        self.assertEqual(order_line.product_id, self.product)
        self.assertEqual(order_line.product_qty, 2.0)
        self.assertEqual(order_line.price_unit, 99.99)

    def test_sorted_extracted_items_puts_price_unit_last(self):
        values = {
            "product_id": self.product,
            "price_unit": 99.99,
            "product_qty": 2.0,
        }
        ordered = self.env["wizard.base.import.pdf.upload.line"]._sorted_extracted_items(
            "purchase.order.line", values
        )
        names = [name for name, _ in ordered]
        self.assertEqual(names, ["product_id", "product_qty", "price_unit"])
        self.assertEqual(dict(ordered), values)
