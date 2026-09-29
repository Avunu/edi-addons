# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from typesafe_sdk import TypeSafeClient

from odoo import api, fields, models

DEFAULT_INSTRUCTIONS = (
    "Which of these document types is this document? Judge by who issued it, "
    "its title and its layout. Documents are usually forwarded by staff, so "
    "the sender may be the shop's own mailbox and the subject may start with "
    "'Fwd:'; the issuer is named in the forwarded message, and 'original "
    "from' (when given) is the real sender. A forwarded copy of a vendor "
    "document is that document, not 'none'. Answer 'none' only when it "
    "clearly is not one of them."
)


class EdiImportRouter(models.Model):
    """A single intake for documents that arrive by email or by printer.

    Every routing decision is an ``edi.exchange.type``: the router asks
    TypeSafe which of its targets a document is, then files the document
    under that type with ``edi.backend.create_record()`` - exactly what
    ``import_from_email`` does for a direct alias - so the type's pinned
    import template and processor take it from there. The email alias is
    only one way in; ERP Printer uploads are another.
    """

    _name = "edi.import.router"
    _description = "EDI Import Router"
    _inherit = ["mail.alias.mixin"]

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    target_ids = fields.One2many(
        "edi.import.router.target", "router_id", string="Targets"
    )
    document_ids = fields.One2many("edi.import.router.document", "router_id")
    document_count = fields.Integer(compute="_compute_document_count")
    confidence_threshold = fields.Float(
        default=0.8,
        help="A document is filed automatically only when TypeSafe's "
        "confidence in its answer is at least this high; anything less waits "
        "for a person to confirm it.",
    )
    ignore_threshold = fields.Float(
        default=0.98,
        help="A document is ignored (rather than sent to review) only when "
        "TypeSafe answers 'none' with at least this much confidence. A wrongly "
        "ignored order is far worse than an extra review item, so this is "
        "stricter than the filing threshold.",
    )
    responsible_user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        help="Gets an activity for every document that needs review.",
    )
    instructions = fields.Text(
        default=DEFAULT_INSTRUCTIONS,
        help="The question put to TypeSafe. The targets' descriptions are "
        "the answers it chooses between.",
    )
    printer_setup = fields.Char(compute="_compute_printer_setup")

    @api.depends("document_ids")
    def _compute_document_count(self):
        counts = dict(
            self.env["edi.import.router.document"]._read_group(
                [("router_id", "in", self.ids)], ["router_id"], ["__count"]
            )
        )
        for router in self:
            router.document_count = counts.get(router, 0)

    def _compute_printer_setup(self):
        for router in self:
            router.printer_setup = (
                "Odoo model: ir.attachment | Attach to model: "
                "edi.import.router | Attach to record ID: %s" % router.id
                if router.id
                else False
            )

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        values["alias_model_id"] = self.env["ir.model"]._get_id(
            "edi.import.router.document"
        )
        values["alias_contact"] = "everyone"
        if self.id:
            values["alias_defaults"] = str({"router_id": self.id})
        return values

    def _typesafe_client(self):
        """A TypeSafe client. Without a stored key the SDK falls back to the
        ``TYPESAFE_API_KEY`` environment variable."""
        api_key = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("edi_import_router.typesafe_api_key")
        )
        return TypeSafeClient(api_key=api_key or None, timeout=30)

    def action_open_documents(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "edi_import_router.edi_import_router_document_action"
        )
        action["domain"] = [("router_id", "=", self.id)]
        action["context"] = {"default_router_id": self.id}
        return action
