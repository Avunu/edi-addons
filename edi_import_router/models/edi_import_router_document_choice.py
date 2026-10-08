# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import _, api, fields, models


class EdiImportRouterDocumentChoice(models.Model):
    """One row of the reviewer's list: a target and TypeSafe's probability for
    it, with a button that routes the document there by hand."""

    _name = "edi.import.router.document.choice"
    _description = "EDI Import Router Document Choice"
    _order = "probability desc, id"

    document_id = fields.Many2one(
        "edi.import.router.document", required=True, ondelete="cascade", index=True
    )
    document_state = fields.Selection(related="document_id.state")
    target_id = fields.Many2one("edi.import.router.target", ondelete="cascade")
    is_none = fields.Boolean(help="TypeSafe's 'none of these' answer.")
    name = fields.Char(compute="_compute_name")
    probability = fields.Float()
    readable = fields.Boolean(
        help="Whether the target's template can read this document at all.",
    )
    note = fields.Char(help="Why this target was not offered to TypeSafe.")

    @api.depends("is_none", "target_id")
    def _compute_name(self):
        for choice in self:
            choice.name = (
                _("None of these (ignore)")
                if choice.is_none
                else choice.target_id.exchange_type_id.name
            )

    def action_route(self):
        """Route the document to this target, or ignore it for 'none'."""
        self.ensure_one()
        document = self.document_id
        document._check_reviewer()
        if self.is_none:
            return document.action_ignore()
        document.sudo()._router_manual_route(self.target_id)
