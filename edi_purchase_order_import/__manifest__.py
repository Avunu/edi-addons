# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "EDI Purchase Order Import",
    "summary": "Auto-confirm purchase orders created from an inbound EDI/"
    "email import and notify a configurable group when it happens.",
    "version": "18.0.1.0.0",
    "category": "Inventory/Purchase",
    "author": "Avunu LLC",
    "website": "https://avu.nu",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        # edi.input.process.template, edi.exchange.record
        "import_from_email",
        # purchase.order, button_confirm
        "purchase",
    ],
    "data": [
        "data/ir_config_parameter.xml",
        "views/res_config_settings_views.xml",
    ],
}
