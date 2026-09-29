# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Template extraction modes that read an email body rather than a PDF.
BODY_MODES = ("html", "plaintext")


class EdiImportRouterTarget(models.Model):
    _name = "edi.import.router.target"
    _description = "EDI Import Router Target"
    _order = "sequence, id"

    router_id = fields.Many2one(
        "edi.import.router", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    exchange_type_id = fields.Many2one(
        "edi.exchange.type",
        string="Exchange Type",
        required=True,
        domain="[('direction', '=', 'input'), ('import_template_id', '!=', False)]",
        ondelete="cascade",
    )
    backend_id = fields.Many2one(
        "edi.backend",
        string="Backend",
        required=True,
        domain="[('backend_type_id', '=', backend_type_id)]",
        help="Defaults to the exchange type's own backend.",
    )
    backend_type_id = fields.Many2one(related="exchange_type_id.backend_type_id")
    source_type = fields.Selection(
        [("any", "Any"), ("email", "Email"), ("print", "Printer")],
        required=True,
        default="any",
        help="Which documents may be filed under this type. Whatever is chosen, "
        "a document is only offered to a type whose template can read it: an "
        "email body needs an HTML or plain-text template, a PDF (printed or "
        "attached to an email) a PDF template.",
    )
    description = fields.Text(
        required=True,
        help="What tells this document type apart: the sender, subject or "
        "title, and distinctive text. This is what TypeSafe reads, so name "
        "the difference when two vendors share a sender (e.g. the dealer).",
    )
    template_mode = fields.Selection(
        related="exchange_type_id.import_template_id.extraction_mode"
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("backend_id") and vals.get("exchange_type_id"):
                exchange_type = self.env["edi.exchange.type"].browse(
                    vals["exchange_type_id"]
                )
                vals["backend_id"] = exchange_type.backend_id.id
        return super().create(vals_list)

    @api.onchange("exchange_type_id")
    def _onchange_exchange_type_id(self):
        self.backend_id = self.exchange_type_id.backend_id

    @api.constrains("source_type", "exchange_type_id")
    def _check_source_type(self):
        for target in self:
            mode = target.template_mode
            if target.source_type == "print" and mode in BODY_MODES:
                raise ValidationError(
                    _(
                        "'%(type)s' uses a %(mode)s template, which cannot "
                        "read a printed PDF.",
                        type=target.exchange_type_id.display_name,
                        mode=mode,
                    )
                )
