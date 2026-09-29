# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    edi_import_router_typesafe_api_key = fields.Char(
        string="TypeSafe API Key (import routers)",
        config_parameter="edi_import_router.typesafe_api_key",
        groups="base.group_system",
        help="API key for TypeSafe AI (typesafe.ai), used to decide which "
        "EDI exchange type an emailed or printed document belongs to. Leave "
        "empty to use the TYPESAFE_API_KEY environment variable; with "
        "neither, every document waits for manual review.",
    )
