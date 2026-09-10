# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
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


@tagged("post_install", "-at_install")
class TestWithoutPattern(BaseCommon):
    """`_without_pattern()` is what lets a pattern engine that already
    consumed the pattern while *selecting* a value (JSONPath, in
    `import_via_xberg`) still run the base module's `_process_value()`
    post-processing tail (date/float conversion, `mapped_ids`,
    `search_field_id`, `default_value`) without duplicating it.

    The naive implementation - `self.new({"pattern": False}, origin=self)` -
    is only correct when `self` is a real, saved record. Called on a record
    that is *itself* already in memory (an onchange, a live preview compute,
    or `odoo.tests.Form`), it builds a NewId whose origin is another NewId;
    `odoo.models.origin_ids()` drops those, so every stored field on the
    twin silently falls back to its field default instead of `self`'s
    actual value. These tests pin both cases.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_field = cls.env.ref("base.field_res_partner__name")
        template = cls.env["base.import.pdf.template"].create(
            {"name": "Engine Test Template", "model_id": cls.env.ref("base.model_res_partner").id}
        )
        cls.line = cls.env["base.import.pdf.template.line"].create(
            {
                "template_id": template.id,
                "related_model": "header",
                # `field_id`'s own ttype is irrelevant here: `date_format`
                # and `mapped_ids` are plain stored fields on the *line*
                # record, independent of what they'd be applied to by
                # `_process_datetime_value()` in a real import.
                "field_id": cls.model_field.id,
                "pattern": r"Name: (.*)",
                "date_format": "*d-*m-*Y",
                "mapped_ids": [(0, 0, {"origin": "N/A", "value": False})],
            }
        )

    def test_real_record_falls_through_to_origin(self):
        twin = self.line._without_pattern()
        self.assertFalse(twin.pattern)
        self.assertEqual(twin.date_format, self.line.date_format)
        self.assertEqual(
            twin.mapped_ids.mapped("origin"), self.line.mapped_ids.mapped("origin")
        )

    def test_in_memory_record_with_origin_still_resolves(self):
        # `twin1` reproduces the trap: a NewId record whose origin is
        # another (real) record - exactly what a live preview compute or an
        # onchange operates on.
        twin1 = self.line.new({}, origin=self.line)
        self.assertFalse(twin1.id)  # NewId.__bool__ is False
        # The naive approach fails here: origin=twin1 (a NewId) is dropped
        # by odoo.models.origin_ids(), so every stored field reads back its
        # bare default.
        naive = self.line.new({"pattern": False}, origin=twin1)
        self.assertFalse(naive.date_format)
        self.assertNotEqual(naive.date_format, self.line.date_format)
        # `_without_pattern()` copies the resolved values instead and must
        # not exhibit that loss.
        twin2 = twin1._without_pattern()
        self.assertFalse(twin2.pattern)
        self.assertEqual(twin2.date_format, self.line.date_format)
        self.assertEqual(
            twin2.mapped_ids.mapped("origin"), self.line.mapped_ids.mapped("origin")
        )
