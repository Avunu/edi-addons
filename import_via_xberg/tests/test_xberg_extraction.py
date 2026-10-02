# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import json
from base64 import b64encode
from os import path

from odoo.exceptions import UserError

from odoo.addons.base.tests.common import BaseCommon


class TestXbergExtraction(BaseCommon):
    """`sample_parts_invoice.pdf` (tests/data/) is a synthetic parts
    invoice laid out like a real-world truck dealer invoice (one ruled
    line-item table with a header row). Every name, address and number
    in it is fictional.
    """

    def _data_file(self, filename):
        with open(path.join(path.dirname(__file__), "data", filename), "rb") as f:
            return f.read()

    def _mixin(self, extraction_mode="xberg"):
        # `wizard.base.import.pdf.mixin` is an AbstractModel: it never gets
        # the `id` magic field (see `BaseModel.__init_subclass__` - magic
        # fields are only added when `not self._abstract`), so `.new()` on
        # the bare mixin itself raises deep inside the ORM cache. Use a
        # concrete model that inherits it instead, exactly like a real
        # caller would.
        return self.env["wizard.base.import.pdf.preview"].new(
            {"extraction_mode": extraction_mode}
        )

    def test_extraction_mode_selection_extended(self):
        selection = dict(
            self.env["base.import.pdf.template"]
            ._fields["extraction_mode"]
            ._description_selection(self.env)
        )
        self.assertIn("xberg", selection)
        # the original mode from base_import_pdf_by_template must still work
        self.assertIn("pypdf", selection)

    def test_preview_wizard_selection_mirrors_template(self):
        # See the comment on WizardBaseImportPdfPreview.extraction_mode:
        # these are two independent Selections, both need the same values.
        selection = dict(
            self.env["wizard.base.import.pdf.preview"]
            ._fields["extraction_mode"]
            ._description_selection(self.env)
        )
        self.assertIn("xberg", selection)

    def test_xberg_extraction_returns_parseable_document(self):
        data = self._data_file("sample_parts_invoice.pdf")
        res = self._mixin().simple_pdf_text_extraction(data)
        self.assertEqual(len(res), 1)
        document = json.loads(res[0])
        self.assertIn("EXAMPLE TRUCK SALES", document["content"])
        self.assertTrue(document["tables"])
        table = document["tables"][0]
        self.assertIn("ITEM", table["cells"][0])
        # the line-item table has a real header row, so its rows should
        # be reachable by header name across the whole table, not just by
        # position - see _transpose_table_cells()
        self.assertTrue(table["cellsByHeader"])
        self.assertEqual(table["cellsByHeader"][0]["ITEM"], "201P/90-0013")
        self.assertEqual(table["cellsByIndex"][0]["2"], "201P/90-0013")

    def test_grouped_parsing_skips_xberg_when_no_template_uses_it(self):
        """`_skip_xberg_grouped_parsing()` must not run a real extraction
        for every attachment when nothing on the instance is configured to
        use it - and must resume trying it once a template does.
        """
        model = self.env["ir.model"]._get("res.partner")
        attachment = self.env["ir.attachment"].create(
            {
                "name": "sample_parts_invoice.pdf",
                "datas": b64encode(
                    self._data_file("sample_parts_invoice.pdf")
                ),
            }
        )
        upload = self.env["wizard.base.import.pdf.upload"].create(
            {"model": "res.partner", "attachment_ids": attachment.ids}
        )
        line = self.env["wizard.base.import.pdf.upload.line"].new(
            {"parent_id": upload.id, "attachment_id": attachment.id}
        )
        # No template at all yet for res.partner -> cannot positively prove
        # xberg is unused, so it must not be skipped.
        self.assertFalse(line._skip_xberg_grouped_parsing())

        pypdf_template = self.env["base.import.pdf.template"].create(
            {"name": "Regex-only", "model_id": model.id, "extraction_mode": "pypdf"}
        )
        # `allowed_template_ids` was already read (and cached, empty) by the
        # `_skip_xberg_grouped_parsing()` call above; its compute only
        # depends on `model`, so creating a template does not by itself
        # invalidate that stale cache.
        upload.invalidate_recordset(["allowed_template_ids"])
        self.assertIn(pypdf_template, upload.allowed_template_ids)
        self.assertTrue(line._skip_xberg_grouped_parsing())

        self.env["base.import.pdf.template"].create(
            {"name": "Xberg template", "model_id": model.id, "extraction_mode": "xberg"}
        )
        upload.invalidate_recordset(["allowed_template_ids"])
        self.assertFalse(line._skip_xberg_grouped_parsing())

        grouped = line._parse_pdf_grouped()
        self.assertIn("xberg", grouped)
        self.assertTrue(grouped["xberg"])

    def test_xberg_config_defaults_timeout(self):
        wizard = self._mixin()
        config = wizard._xberg_config()
        self.assertIn("timeout_secs", config)
        self.assertEqual(config["timeout_secs"], 300)

    def test_xberg_config_merges_template_json(self):
        template = self.env["base.import.pdf.template"].create(
            {
                "name": "Configured template",
                "model_id": self.env.ref("base.model_res_partner").id,
                "extraction_mode": "xberg",
                "xberg_config": '{"ocr": {"enabled": true}}',
            }
        )
        wizard = self.env["wizard.base.import.pdf.preview"].new(
            {"extraction_mode": "xberg", "template_id": template.id}
        )
        config = wizard._xberg_config()
        self.assertEqual(config["ocr"], {"enabled": True})
        # the default timeout is still filled in alongside the template's
        # own config, not replaced by it
        self.assertIn("timeout_secs", config)

    def test_xberg_extraction_with_invalid_config_json_fails_gracefully(self):
        """A malformed `xberg_config` must surface as the base module's
        standard "could not extract" UserError, like any other extraction
        failure - never a raw traceback."""
        template = self.env["base.import.pdf.template"].create(
            {
                "name": "Bad config template",
                "model_id": self.env.ref("base.model_res_partner").id,
                "extraction_mode": "xberg",
                "xberg_config": "not valid json",
            }
        )
        wizard = self.env["wizard.base.import.pdf.preview"].new(
            {"extraction_mode": "xberg", "template_id": template.id}
        )
        data = self._data_file("sample_parts_invoice.pdf")
        with self.assertRaises(UserError):
            wizard.simple_pdf_text_extraction(data)
