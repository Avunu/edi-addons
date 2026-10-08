# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import base64
import io
from unittest.mock import MagicMock, patch

from reportlab.pdfgen import canvas
from typesafe_sdk import TypeSafeError

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form

from odoo.addons.base.tests.common import BaseCommon
from odoo.addons.queue_job.tests.common import trap_jobs

from odoo.addons.edi_import_router.models import edi_import_router as router_module
from odoo.addons.edi_import_router.models.edi_import_router_target import (
    reads_body,
    reads_pdf,
)


def _pdf(text="Quote Q-1001 FleetPride"):
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, text)
    pdf.save()
    return buf.getvalue()


def _answer(choice, confidence=0.95):
    answer = MagicMock()
    answer.choice = choice
    answer.confidence = confidence
    answer.probabilities = {choice: confidence}
    return answer


class TestEdiImportRouter(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Template = cls.env["base.import.pdf.template"]
        model = cls.env["ir.model"]._get("res.partner")
        backend_type = cls.env["edi.backend.type"].create(
            {"name": "Router Test Type", "code": "router_test_type"}
        )
        cls.backend = cls.env["edi.backend"].create(
            {"name": "Router Test Backend", "backend_type_id": backend_type.id}
        )

        def exchange_type(code, mode):
            template = Template.create(
                {"name": code, "model_id": model.id, "extraction_mode": mode}
            )
            return cls.env["edi.exchange.type"].create(
                {
                    "name": code,
                    "code": code,
                    "direction": "input",
                    "backend_type_id": backend_type.id,
                    "backend_id": cls.backend.id,
                    "import_template_id": template.id,
                    "quick_exec": False,
                }
            )

        cls.html_type = exchange_type("router_html", "html")
        cls.pdf_type = exchange_type("router_pdf", "pypdf")
        cls.router = cls.env["edi.import.router"].create(
            {"name": "Test router", "alias_name": "router-test"}
        )
        Target = cls.env["edi.import.router.target"]
        cls.html_target = Target.create(
            {
                "router_id": cls.router.id,
                "exchange_type_id": cls.html_type.id,
                "description": "Parts supplier order confirmation",
            }
        )
        cls.pdf_target = Target.create(
            {
                "router_id": cls.router.id,
                "exchange_type_id": cls.pdf_type.id,
                "description": "FleetPride quote",
            }
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "edi_import_router.typesafe_api_key", "test-key"
        )
        cls.printer = cls.env["res.users"].create(
            {
                "name": "ERP Printer",
                "login": "erp_printer",
                "groups_id": [
                    (6, 0, [cls.env.ref("edi_import_router.group_import_router_intake").id,
                            cls.env.ref("base.group_user").id])
                ],
            }
        )

    # -- helpers -----------------------------------------------------------

    def _email(self, body="<p>Order</p>", pdf=False):
        with trap_jobs():
            doc = self.env["edi.import.router.document"].message_new(
                {"subject": "Order", "body": body, "email_from": "a@b.c", "message_id": "<m1@x>"},
                {"router_id": self.router.id},
            )
        if pdf:
            self._attach(doc, _pdf())
        return doc

    def _attach(self, doc, data):
        return self.env["ir.attachment"].create(
            {
                "name": "a.pdf",
                "datas": base64.b64encode(data),
                "mimetype": "application/pdf",
                "res_model": doc._name,
                "res_id": doc.id,
            }
        )

    def _print(self, data=None, user=None):
        env = self.env(user=user) if user else self.env
        with trap_jobs():
            att = env["ir.attachment"].create(
                {
                    "name": "Quote",
                    "datas": base64.b64encode(data or _pdf()),
                    "mimetype": "application/pdf",
                    "res_model": "edi.import.router",
                    "res_id": self.router.id,
                    "description": "Printed by X on Y",
                }
            )
        return self.env["edi.import.router.document"].search(
            [("router_id", "=", self.router.id)], order="id desc", limit=1
        ), att

    def _run(self, doc, choice, confidence=0.95, error=None):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        if error:
            client.system_one.side_effect = error
        else:
            response = MagicMock()
            response.choices = {"exchange_type": _answer(choice, confidence)} if choice else {}
            client.system_one.return_value = response
        with patch.object(router_module, "TypeSafeClient", return_value=client):
            doc._router_classify_and_dispatch()
        return client

    # -- intake ------------------------------------------------------------

    def test_alias_targets_document_model(self):
        alias = self.router.alias_id
        self.assertEqual(alias.alias_model_id.model, "edi.import.router.document")
        self.assertIn(str(self.router.id), alias.alias_defaults)

    def test_email_intake_queues_job(self):
        with trap_jobs() as trap:
            doc = self.env["edi.import.router.document"].message_new(
                {"subject": "Order", "body": "<p>x</p>", "email_from": "a@b.c", "message_id": "<1@x>"},
                {"router_id": self.router.id},
            )
        self.assertEqual((doc.source_type, doc.state, doc.name), ("email", "pending", "Order"))
        trap.assert_enqueued_job(doc._router_classify_and_dispatch, args=(), kwargs={})

    def test_print_intake_by_printer_user(self):
        doc, att = self._print(user=self.printer)
        self.assertEqual((doc.source_type, doc.state), ("print", "pending"))
        self.assertEqual((att.res_model, att.res_id), (doc._name, doc.id))
        with self.assertRaises(AccessError):
            self.router.with_user(self.printer).write({"name": "Hacked"})

    def test_print_intake_refused_without_group(self):
        user = self.env["res.users"].create({"name": "Nobody", "login": "nobody_r"})
        with self.assertRaises(AccessError):
            self._print(user=user)

    def test_duplicate_print_ignored(self):
        # One byte string sent twice, as an outbox retry does: a fresh print
        # never matches, because Print to PDF stamps a creation date.
        data = _pdf("same")
        first, _att = self._print(data=data)
        self.assertEqual(first.state, "pending")
        second, _att = self._print(data=data)
        self.assertNotEqual(first, second)
        self.assertEqual(second.state, "ignored")

    # -- offering ----------------------------------------------------------

    def test_offered_targets_by_capability(self):
        email = self._email()
        self.assertEqual(email._router_offered_targets(), self.html_target)
        email_pdf = self._email(pdf=True)
        self.assertEqual(email_pdf._router_offered_targets(), self.html_target | self.pdf_target)
        printed, _att = self._print()
        self.assertEqual(printed._router_offered_targets(), self.pdf_target)
        self.pdf_target.source_type = "email"
        self.assertFalse(printed._router_offered_targets())

    def test_extraction_modes_by_source(self):
        # xberg parses HTML as readily as a PDF, so it reads both
        self.assertEqual((reads_body("html"), reads_pdf("html")), (True, False))
        self.assertEqual((reads_body("plaintext"), reads_pdf("plaintext")), (True, False))
        self.assertEqual((reads_body("pypdf"), reads_pdf("pypdf")), (False, True))
        self.assertEqual((reads_body("xberg"), reads_pdf("xberg")), (True, True))
        self.assertEqual((reads_body(False), reads_pdf(False)), (False, False))

    def test_both_readers_target_gets_email_body(self):
        both = patch.multiple(
            "odoo.addons.edi_import_router.models.edi_import_router_document",
            reads_body=lambda mode: True,
            reads_pdf=lambda mode: True,
        )
        email = self._email()
        with both:
            self.assertEqual(
                email._router_offered_targets(), self.html_target | self.pdf_target
            )
            content, name = email._router_exchange_file(self.pdf_target)
        self.assertEqual(content, b"<p>Order</p>")
        self.assertTrue(name.endswith(".html"))

    # -- classification ----------------------------------------------------

    def test_email_routed_with_body(self):
        doc = self._email(body="<p>ORD-1</p>")
        client = self._run(doc, str(self.html_target.id))
        self.assertEqual(doc.state, "routed")
        exchange = doc.exchange_record_id
        self.assertEqual(exchange.type_id, self.html_type)
        self.assertEqual(exchange.edi_exchange_state, "input_received")
        self.assertEqual(base64.b64decode(exchange.exchange_file), b"<p>ORD-1</p>")
        criteria = client.system_one.call_args.kwargs["questions"]["exchange_type"]
        self.assertIn("none", criteria.criteria)

    def test_print_routed_with_pdf(self):
        doc, _att = self._print()
        self._run(doc, str(self.pdf_target.id))
        self.assertEqual(doc.state, "routed")
        self.assertTrue(doc.exchange_record_id.exchange_file)
        self.assertIn("Quote Q-1001", doc._router_typesafe_state()["pdf text"])

    def test_none_is_ignored(self):
        doc = self._email(pdf=True)  # both targets can read it
        self._run(doc, "none", confidence=0.99)
        self.assertEqual(doc.state, "ignored")
        self.assertFalse(doc.exchange_record_id)

    def test_soft_none_needs_review(self):
        doc = self._email(pdf=True)
        self._run(doc, "none", confidence=0.93)
        self.assertEqual(doc.state, "review")
        self.assertIn("93%", doc.error_message)

    def test_choices_list_every_target_with_probability(self):
        doc = self._email(pdf=True)
        self._run(doc, "none", confidence=0.6)
        choices = {c.name: c for c in doc.choice_ids}
        self.assertEqual(set(choices), {"router_html", "router_pdf", "None of these (ignore)"})
        self.assertAlmostEqual(choices["None of these (ignore)"].probability, 0.6)
        self.assertEqual(doc.choice_ids[0].name, "None of these (ignore)")  # best first
        self.assertTrue(all(c.readable for c in doc.choice_ids))

    def test_none_with_unreadable_target_needs_review(self):
        doc = self._email()  # no PDF, so the PDF target cannot be offered
        client = self._run(doc, "none", confidence=0.99)
        self.assertEqual(doc.state, "review")
        self.assertIn("router_pdf", doc.error_message)
        criteria = client.system_one.call_args.kwargs["questions"]["exchange_type"].criteria
        self.assertNotIn(str(self.pdf_target.id), criteria)
        note = " ".join(doc.message_ids.mapped("body"))
        self.assertIn("Not offered to TypeSafe", note)
        choices = {c.name: c for c in doc.choice_ids}
        self.assertFalse(choices["router_pdf"].readable)
        self.assertIn("needs a PDF", choices["router_pdf"].note)

    def test_route_by_hand_from_choice(self):
        doc = self._email()
        self._run(doc, "none", confidence=0.5)
        self.assertEqual(doc.state, "review")
        choice = doc.choice_ids.filtered(lambda c: c.target_id == self.html_target)
        choice.action_route()
        self.assertEqual(doc.state, "routed")
        self.assertEqual(doc.target_id, self.html_target)
        self.assertEqual(doc.exchange_record_id.type_id, self.html_type)

    def test_route_by_hand_rescues_ignored_document(self):
        doc = self._email(pdf=True)
        self._run(doc, "none", confidence=0.99)
        self.assertEqual(doc.state, "ignored")
        doc.choice_ids.filtered(lambda c: c.target_id == self.pdf_target).action_route()
        self.assertEqual(doc.state, "routed")
        self.assertEqual(doc.exchange_record_id.type_id, self.pdf_type)

    def test_none_choice_ignores(self):
        doc = self._email()
        self._run(doc, "none", confidence=0.5)
        doc.choice_ids.filtered("is_none").action_route()
        self.assertEqual(doc.state, "ignored")

    def test_routed_document_cannot_be_rerouted(self):
        doc = self._email()
        self._run(doc, str(self.html_target.id))
        with self.assertRaises(UserError):
            doc.choice_ids.filtered(lambda c: c.target_id == self.html_target).action_route()
        with self.assertRaises(UserError):
            doc.action_reclassify()

    def test_review_keeps_one_open_activity(self):
        self.router.responsible_user_id = self.env.user
        doc = self._email()
        for _i in range(2):
            self._run(doc, str(self.html_target.id), confidence=0.3)
        self.assertEqual(len(doc.activity_ids), 1)

    def test_reads_column(self):
        self.assertEqual(self.html_target.reads, "Email body")
        self.assertEqual(self.pdf_target.reads, "PDF")

    def test_original_sender_from_forwarded_header(self):
        body = (
            "<div>FYI<br>---------- Forwarded message ---------<br>"
            "From: <b>OPC</b> &lt;parts-counter@supplier.example&gt;<br>"
            "Date: Mon<br>Subject: OPC Order Confirmation</div><p>Thanks</p>"
        )
        doc = self._email(body=body)
        state = doc._router_typesafe_state()
        self.assertIn("parts-counter@supplier.example", state["original from"])
        self.assertEqual(state["from"], "a@b.c")
        self.assertNotIn("original from", self._email(body="<p>x</p>")._router_typesafe_state())

    def test_low_confidence_needs_review_with_activity(self):
        self.router.responsible_user_id = self.env.user
        doc = self._email()
        self._run(doc, str(self.html_target.id), confidence=0.3)
        self.assertEqual(doc.state, "review")
        self.assertTrue(doc.activity_ids)

    def test_typesafe_error_needs_review(self):
        doc = self._email()
        self._run(doc, None, error=TypeSafeError("boom"))
        self.assertEqual((doc.state, doc.error_message), ("review", "boom"))

    def test_missing_key_needs_review(self):
        self.env["ir.config_parameter"].sudo().set_param("edi_import_router.typesafe_api_key", "")
        doc = self._email()
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("TYPESAFE_API_KEY", None)
            doc._router_classify_and_dispatch()
        self.assertEqual(doc.state, "review")
        self.assertIn("API key", doc.error_message)

    def test_pdf_target_without_pdf_needs_review_on_manual_dispatch(self):
        doc = self._email()
        doc.write({"state": "review", "target_id": self.pdf_target.id})
        doc.action_dispatch()
        self.assertEqual(doc.state, "review")
        self.assertIn("no PDF", doc.error_message)

    def test_manual_dispatch(self):
        doc = self._email()
        doc.write({"state": "review", "target_id": self.html_target.id})
        doc.action_dispatch()
        self.assertEqual(doc.state, "routed")
        self.assertEqual(doc.exchange_record_id.type_id, self.html_type)

    def test_message_update_redirects_to_new(self):
        doc = self._email()
        with trap_jobs():
            other = doc.message_update(
                {"subject": "Again", "body": "<p>2</p>", "message_id": "<2@x>"},
                {"router_id": self.router.id},
            )
        self.assertNotEqual(doc, other)
