# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import base64
import io
import logging
import re

import pypdf
from typesafe_sdk import (
    Choice,
    TypeSafeAPIConnectionError,
    TypeSafeError,
    TypeSafeRateLimitError,
)

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.queue_job.exception import RetryableJobError

from .edi_import_router_target import BODY_MODES

_logger = logging.getLogger(__name__)

# The most text sent to TypeSafe per source (email body, PDF). Only input
# tokens are billed, and the sender, title and first page settle the question.
TEXT_LIMIT = 8000
NONE_CHOICE = "none"
NONE_DESCRIPTION = (
    "Clearly not one of the other document types: Google's mail-forwarding "
    "confirmation email, marketing or newsletters, a printer test page or a "
    "blank page. A forwarded ('Fwd:') copy of a vendor's order, quote or "
    "confirmation is NOT this; it is that vendor's document."
)
# "---------- Forwarded message ---------" (Gmail) / "-----Original Message-----"
# (Outlook), then the original header block's From line.
_FORWARDED_FROM_RE = re.compile(
    r"(?:forwarded message|original message)\W*?\n(?:.*\n){0,3}?\s*from:\s*(.+)",
    re.IGNORECASE,
)
_FROM_LINE_RE = re.compile(r"^\s*from:\s*(.*@.*)$", re.IGNORECASE | re.MULTILINE)
# A retryable failure is retried this many times, then reviewed by a person.
MAX_RETRIES = 3


class EdiImportRouterDocument(models.Model):
    """One emailed or printed document on its way to an exchange type."""

    _name = "edi.import.router.document"
    _description = "EDI Import Router Document"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True)
    router_id = fields.Many2one(
        "edi.import.router", required=True, ondelete="cascade", index=True
    )
    source_type = fields.Selection(
        [("email", "Email"), ("print", "Printer")], required=True, default="email"
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("routed", "Routed"),
            ("review", "Needs Review"),
            ("ignored", "Ignored"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        index=True,
        tracking=True,
    )
    target_id = fields.Many2one("edi.import.router.target", string="Target")
    confidence = fields.Float()
    probabilities = fields.Json()
    probabilities_display = fields.Text(compute="_compute_probabilities_display")
    error_message = fields.Text()
    exchange_record_id = fields.Many2one("edi.exchange.record", readonly=True)
    routed_record = fields.Reference(
        selection="_selection_routed_record", compute="_compute_routed_record"
    )
    # email
    email_from = fields.Char()
    message_id = fields.Char()
    email_body = fields.Binary(attachment=True)
    # print
    print_source = fields.Char(help="Who printed it, and from where.")
    checksum = fields.Char(index=True)

    # ------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------

    @api.model
    def _selection_routed_record(self):
        models_ = self.env["ir.model"].sudo().search([("transient", "=", False)])
        return [(m.model, m.name) for m in models_]

    @api.depends("probabilities")
    def _compute_probabilities_display(self):
        for doc in self:
            names = {
                str(t.id): t.exchange_type_id.name
                for t in doc.router_id.target_ids.with_context(active_test=False)
            }
            names[NONE_CHOICE] = _("None of these (ignore)")
            ranked = sorted((doc.probabilities or {}).items(), key=lambda kv: -kv[1])
            doc.probabilities_display = "\n".join(
                "%s: %.0f%%" % (names.get(key, key), value * 100)
                for key, value in ranked
            )

    @api.depends("exchange_record_id.model", "exchange_record_id.res_id")
    def _compute_routed_record(self):
        for doc in self:
            record = doc.exchange_record_id.record
            doc.routed_record = "%s,%s" % (record._name, record.id) if record else False

    # ------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------

    def message_new(self, msg_dict, custom_values=None):
        custom_values = dict(custom_values or {})
        body = msg_dict.get("body") or ""
        custom_values.update(
            source_type="email",
            email_from=msg_dict.get("email_from"),
            message_id=msg_dict.get("message_id"),
            email_body=base64.b64encode(body.encode()),
        )
        doc = super().message_new(msg_dict, custom_values)
        doc._router_enqueue()
        return doc

    def message_update(self, msg_dict, update_vals=None):
        """Never treat an inbound email as an update to an earlier document.

        Mail clients that keep separate forwards under one subject share a
        References chain, and Odoo resolves a "reply" from that chain alone;
        every routed email is its own document, as in
        ``import_from_email``'s ``edi.exchange.record.message_update``.
        """
        return self.message_new(msg_dict, update_vals)

    @api.model
    def _intake_attachment(self, attachment):
        """Turn a PDF attached to a router into a document (ERP Printer)."""
        router = self.env["edi.import.router"].browse(attachment.res_id)
        if attachment.checksum and self.search_count(
            [("router_id", "=", router.id), ("checksum", "=", attachment.checksum)]
        ):
            # Only an outbox retry after a lost response re-sends identical
            # bytes: Print to PDF stamps a creation date on every new print.
            original = self.search(
                [("router_id", "=", router.id), ("checksum", "=", attachment.checksum)],
                limit=1,
            )
            state, note = "ignored", _(
                "Duplicate of %s: same file contents.", original.display_name
            )
        else:
            state, note = "pending", False
        doc = self.create(
            {
                "name": attachment.name,
                "router_id": router.id,
                "source_type": "print",
                "print_source": attachment.description,
                "checksum": attachment.checksum,
                "state": state,
            }
        )
        attachment.write({"res_model": self._name, "res_id": doc.id})
        doc.message_post(body=note or _("Printed document received."), attachment_ids=attachment.ids)
        if state == "pending":
            doc._router_enqueue()
        return doc

    def _router_enqueue(self):
        # As the superuser, as the mail gateway effectively is: a printer
        # upload's user may only upload, and the job creates EDI records.
        self.with_user(SUPERUSER_ID).with_delay(
            description=_("Route %s to an exchange type", self.name),
            max_retries=MAX_RETRIES,
        )._router_classify_and_dispatch()

    # ------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------

    def _router_pdf(self):
        """The first PDF on this document (the print itself, or an email's attachment)."""
        self.ensure_one()
        return self.env["ir.attachment"].sudo().search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("mimetype", "=", "application/pdf"),
            ],
            order="id",
            limit=1,
        )

    def _router_pdf_text(self, attachment):
        try:
            reader = pypdf.PdfReader(io.BytesIO(base64.b64decode(attachment.datas)))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:  # noqa: BLE001 - a bad PDF is a review case, not a crash
            _logger.warning("Could not read PDF text of %s", self.display_name)
            return "", 0
        return text[:TEXT_LIMIT], len(reader.pages)

    def _router_typesafe_state(self):
        """The document as TypeSafe sees it."""
        self.ensure_one()
        state = {}
        if self.source_type == "email":
            body = base64.b64decode(self.email_body or b"").decode(errors="replace")
            text = html2plaintext(body)
            state.update(
                {
                    "subject": self.name,
                    "from": self.email_from,
                    "original from": self._router_original_sender(text),
                    "body": text[:TEXT_LIMIT],
                }
            )
        else:
            state.update({"file name": self.name, "printed by": self.print_source})
        pdf = self._router_pdf()
        if pdf:
            text, pages = self._router_pdf_text(pdf)
            state["attachment file name"] = pdf.name
            state["pages"] = pages
            if text.strip():
                state["pdf text"] = text
        return {k: v for k, v in state.items() if v not in (None, False, "")}

    @staticmethod
    def _router_original_sender(text):
        """The sender of a forwarded email, read from its forwarded header.

        Staff forward vendor mail by hand, so ``email_from`` is the shop's
        own mailbox and the vendor's address appears only in the quoted
        header block (or nowhere, when the mail client dropped it).
        """
        head = text[:TEXT_LIMIT]
        match = _FORWARDED_FROM_RE.search(head) or _FROM_LINE_RE.search(head)
        return match.group(1).strip()[:200] if match else None

    def _router_offered_targets(self):
        """The router's targets that accept this source and can read its file."""
        self.ensure_one()
        has_pdf = bool(self._router_pdf())
        targets = self.router_id.target_ids.filtered("active")

        def offered(target):
            if target.source_type not in ("any", self.source_type):
                return False
            if target.template_mode in BODY_MODES:
                return self.source_type == "email"
            return has_pdf

        return targets.filtered(offered)

    def _router_typesafe_criteria(self, targets):
        criteria = {
            str(target.id): {
                "document type": target.exchange_type_id.name,
                "description": target.description,
            }
            for target in targets
        }
        criteria[NONE_CHOICE] = {"description": NONE_DESCRIPTION}
        return criteria

    def _router_exchange_file(self, target):
        """``(bytes, filename)`` in the form the target's template reads."""
        self.ensure_one()
        if target.template_mode in BODY_MODES:
            if self.source_type != "email":
                raise UserError(_("A printed document has no email body to read."))
            name = "%s.html" % (self.message_id or self.id)
            return base64.b64decode(self.email_body or b""), name
        pdf = self._router_pdf()
        if not pdf:
            raise UserError(_("This document has no PDF for a PDF template to read."))
        return base64.b64decode(pdf.datas), pdf.name

    # ------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------

    def _router_classify_and_dispatch(self):
        """Job: ask TypeSafe which target this is, then act on the answer."""
        self.ensure_one()
        if self.state not in ("pending", "review", "error"):
            return
        targets = self._router_offered_targets()
        if not targets:
            return self._router_set_review(
                _("No target of this router can read this document.")
            )
        router = self.router_id
        try:
            with router._typesafe_client() as client:
                response = client.system_one(
                    state=self._router_typesafe_state(),
                    questions={
                        "exchange_type": Choice(
                            instructions=router.instructions,
                            criteria=self._router_typesafe_criteria(targets),
                        )
                    },
                )
        except (TypeSafeRateLimitError, TypeSafeAPIConnectionError) as err:
            if self.env.context.get("queue_job__no_delay"):
                return self._router_set_review(str(err))
            raise RetryableJobError(str(err), seconds=60) from err
        except TypeSafeError as err:
            _logger.exception("TypeSafe routing failed for %s", self.display_name)
            return self._router_set_review(str(err))
        answer = response.choices.get("exchange_type")
        if not answer:
            return self._router_set_review(_("TypeSafe returned no answer."))
        self.write(
            {
                "confidence": answer.confidence,
                "probabilities": dict(answer.probabilities),
            }
        )
        if answer.choice == NONE_CHOICE:
            if answer.confidence >= router.ignore_threshold:
                self.write({"state": "ignored", "error_message": False})
                return self.message_post(
                    body=_("Not a document for any of the targets.")
                )
            return self._router_set_review(
                _(
                    "TypeSafe thinks this is not one of the targets, but only "
                    "%.0f%% sure (ignoring needs %.0f%%).",
                    answer.confidence * 100,
                    router.ignore_threshold * 100,
                )
            )
        if answer.confidence < router.confidence_threshold:
            return self._router_set_review(
                _("TypeSafe is not confident enough (%.0f%%).", answer.confidence * 100)
            )
        target = targets.filtered(lambda t: str(t.id) == answer.choice)
        if not target:
            return self._router_set_review(
                _("TypeSafe chose an unknown target (%s).", answer.choice)
            )
        self._router_dispatch(target)

    def _router_dispatch(self, target):
        """File this document under the target's exchange type."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                content, filename = self._router_exchange_file(target)
                exchange = target.backend_id.sudo().create_record(
                    target.exchange_type_id.code,
                    {
                        "exchange_file": base64.b64encode(content),
                        "exchange_filename": filename,
                        # The whole document is in hand, so there is no
                        # receive round-trip: without "input_received" a
                        # quick_exec type would never pick this record up
                        # (see import_from_email).
                        "edi_exchange_state": "input_received",
                    },
                )
        except Exception as err:  # noqa: BLE001 - shown to the reviewer
            _logger.exception("Dispatching %s failed", self.display_name)
            return self._router_set_review(str(err))
        self.write(
            {
                "state": "routed",
                "target_id": target.id,
                "exchange_record_id": exchange.id,
                "error_message": False,
            }
        )
        self.message_post(
            body=_(
                "Filed under %(type)s (%(exchange)s).",
                type=target.exchange_type_id.display_name,
                exchange=exchange.display_name,
            )
        )
        return exchange

    def _router_set_review(self, reason):
        self.ensure_one()
        self.write({"state": "review", "error_message": reason})
        user = self.router_id.responsible_user_id
        if user:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=_("Choose a document type"),
                note=reason,
            )

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------

    def _check_reviewer(self):
        self.check_access("write")

    def action_dispatch(self):
        """File under the target a reviewer picked."""
        self._check_reviewer()
        for doc in self.sudo():
            if not doc.target_id:
                raise UserError(_("Choose a target first."))
            if doc.state not in ("review", "error", "pending"):
                raise UserError(_("Only documents waiting for review can be dispatched."))
            doc.activity_unlink(["mail.mail_activity_data_todo"])
            doc._router_dispatch(doc.target_id)

    def action_reclassify(self):
        self._check_reviewer()
        for doc in self:
            doc.write({"state": "pending", "error_message": False})
            doc._router_enqueue()

    def action_ignore(self):
        self._check_reviewer()
        self.sudo().activity_unlink(["mail.mail_activity_data_todo"])
        self.write({"state": "ignored"})
