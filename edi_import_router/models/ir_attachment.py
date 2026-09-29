# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import api, models

ROUTER_MODEL = "edi.import.router"
INTAKE_GROUP = "edi_import_router.group_import_router_intake"


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        for attachment in attachments.filtered(
            lambda a: a.res_model == ROUTER_MODEL
            and a.res_id
            and not a.res_field
            and a.mimetype == "application/pdf"
        ):
            self.env["edi.import.router.document"].sudo()._intake_attachment(
                attachment.sudo()
            )
        return attachments

    def check(self, mode, values=None):
        """Let the printer's user upload to a router without being able to edit it.

        Core requires write access to the record an attachment is added to.
        The printer's API key sits on client PCs, so that user must never
        hold write access to router configuration: for uploads to a router,
        read access (which the intake group has) is enough.
        """
        if (
            mode == "create"
            and values
            and values.get("res_model") == ROUTER_MODEL
            and values.get("res_id")
            and self.env.user.has_group(INTAKE_GROUP)
        ):
            self.env[ROUTER_MODEL].browse(values["res_id"]).exists().check_access("read")
            return
        return super().check(mode, values)
