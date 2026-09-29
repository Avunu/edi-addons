# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""A row (or the whole document) that `odoo.tests.Form` refuses to save -
typically a required field nothing filled in - used to escape as a bare
`AssertionError`: no `exchange_error` on the EDI record, no chatter
notification, just a raw traceback wherever the caller happened to let it
land. These pin the replacement: a `UserError`, naming the row and the
field by its real label, which `edi_backend.exchange_process()`'s own
`_swallable_exceptions()` already knows how to turn into a clean state +
message + notification - see `wizards/wizard_base_import_pdf_upload.py`.
"""
from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.base.tests.common import BaseCommon

# post_install, not at_install - same reason as this module's other tests:
# a res.partner create() at_install can die on a not-yet-attached ORM
# default `account` adds to that model.
_TAGS = ("post_install", "-at_install")


@tagged(*_TAGS)
class TestChildLineErrorReporting(BaseCommon):
    """A `lines` template whose row leaves a required field of the CHILD
    model unset - the same shape as the live failure this was built for
    (a purchase order line with no product): one row extracts fine except
    for one field.

    Uses `res.partner.child_ids` (comodel `res.partner`, its own `name`
    required) rather than a more `import_create_missing`-flavoured
    one2many: it's the "Contacts" tab of the stock partner form, present
    unconditionally - unlike `bank_ids`, which some installs only show to
    users in an accounting group, and `odoo.tests.Form` excludes a field
    the current user's groups hide from the view entirely.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Error Reporting Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "child_field_id": cls.env.ref("base.field_res_partner__child_ids").id,
            }
        )
        # One "lines" line, so there's exactly one row to build - but it
        # never fills the child contact's `name`. `email` (rather than
        # `ref`) because the quick-create sub-form `child_ids.new()` uses
        # only shows a handful of fields - `ref` isn't among them, and
        # setting a field Form doesn't expose raises its OWN, unrelated
        # AssertionError ("... was not found in the view").
        cls.env["base.import.pdf.template.line"].create(
            {
                "template_id": cls.template.id,
                "related_model": "lines",
                "field_id": cls.env.ref("base.field_res_partner__email").id,
                "pattern": r"Email: (\S+)",
            }
        )
        # `name` is only CONDITIONALLY required on res.partner - the view's
        # own `required="type == \'contact\'"` - so it must be forced to
        # 'contact' for the sub-form's own exit-time check (the one this
        # test targets) to fire at all; left at its default, the row saves
        # fine at that point and the SAME condition only bites later, when
        # the top-level Form itself is saved (covered by
        # `TestHeaderErrorReporting` instead - a different code path with
        # its own message shape, see `_REQUIRED_FIELD_RE`).
        type_field = cls.env.ref("base.field_res_partner__type")
        contact_option = cls.env["ir.model.fields.selection"].search(
            [("field_id", "=", type_field.id), ("value", "=", "contact")], limit=1
        )
        cls.env["base.import.pdf.template.line"].create(
            {
                "template_id": cls.template.id,
                "related_model": "lines",
                "field_id": type_field.id,
                "value_type": "fixed",
                "fixed_value_selection": contact_option.id,
            }
        )

    def _wizard_line(self, text):
        # `.create()` silently drops an explicit value for `template_id`
        # (a stored compute with no inverse - only `attachment_id`-driven
        # auto-detection is honored there); `.write()` afterwards does not
        # have that restriction, and is how `import_from_email` sets a
        # known template without an attachment too (see its own
        # `pinned_template_id`/`_compute_template_id` override).
        line = self.env["wizard.base.import.pdf.upload.line"].create({})
        line.write({"template_id": self.template.id, "data": text})
        return line

    def test_child_line_assertion_becomes_a_friendly_usererror(self):
        line = self._wizard_line("Email: x1@example.com\n")
        with self.assertRaises(UserError) as capture:
            line._process_form()
        message = str(capture.exception)
        self.assertIn("Row 1", message)
        # The real field label, not the raw Python-internal phrasing
        # ("'name' is a required field").
        self.assertIn("Name", message)
        self.assertNotIn("'name'", message)
        # The row's own other values, to help identify WHICH row.
        self.assertIn("email=x1@example.com", message)

    def test_no_document_is_left_half_created(self):
        before = self.env["res.partner"].search_count([("ref", "=", "X1")])
        line = self._wizard_line("Email: x1@example.com\n")
        with self.assertRaises(UserError):
            line._process_form()
        after = self.env["res.partner"].search_count([("ref", "=", "X1")])
        self.assertEqual(before, after)


@tagged(*_TAGS)
class TestHeaderErrorReporting(BaseCommon):
    """The OUTER Form's own required-field check - the base module's
    `_create_or_update_record()` already converts this to a `UserError`,
    just with the bare assertion text; this re-words it the same way.
    `res.partner` itself, with no template line mapping anything to its
    own required `name` at all - `res.partner` is guaranteed a normal,
    Form()-compatible default form view, unlike a model with no dedicated
    one of its own (e.g. `res.partner.category`)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Header Error Reporting Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
            }
        )

    def test_header_assertion_is_reworded(self):
        line = self.env["wizard.base.import.pdf.upload.line"].create({})
        line.write({"template_id": self.template.id, "data": "irrelevant\n"})
        with self.assertRaises(UserError) as capture:
            line._process_form()
        message = str(capture.exception)
        self.assertIn("Name", message)
        self.assertNotIn("'name' is a required field", message)


@tagged(*_TAGS)
class TestUnexpectedErrorReporting(BaseCommon):
    """`_process_form()`'s outer safety net - anything besides
    `UserError`/`RedirectWarning`/a DB-transaction error becomes a clean
    `UserError` too, with the real exception chained (`from err`) so
    `exchange_process()` still captures its full traceback."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["base.import.pdf.template"].create(
            {
                "name": "Unexpected Error Test Template",
                "model_id": cls.env.ref("base.model_res_partner").id,
            }
        )

    def test_unexpected_exception_becomes_a_usererror(self):
        line = self.env["wizard.base.import.pdf.upload.line"].create({})
        line.write({"template_id": self.template.id, "data": "irrelevant\n"})
        # A record instance can't be monkeypatched directly (Odoo blocks
        # arbitrary attribute assignment on a recordset); patch the class
        # method instead, scoped to this test.
        with mock.patch.object(
            type(line), "_set_header_values", side_effect=ValueError("boom")
        ):
            with self.assertRaises(UserError) as capture:
                line._process_form()
        message = str(capture.exception)
        self.assertIn("ValueError", message)
        self.assertIn("boom", message)
        self.assertIsInstance(capture.exception.__cause__, ValueError)

    def test_db_transaction_error_is_not_converted(self):
        import psycopg2

        line = self.env["wizard.base.import.pdf.upload.line"].create({})
        line.write({"template_id": self.template.id, "data": "irrelevant\n"})
        with mock.patch.object(
            type(line),
            "_set_header_values",
            side_effect=psycopg2.IntegrityError("constraint violation"),
        ):
            with self.assertRaises(psycopg2.IntegrityError):
                line._process_form()
