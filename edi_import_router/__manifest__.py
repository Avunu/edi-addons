# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "EDI Import Router",
    "summary": "One inbox for emailed and printed documents: TypeSafe picks "
    "the EDI exchange type (and so the import template) for each one.",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "author": "Avunu LLC",
    "website": "https://avu.nu",
    "license": "AGPL-3",
    "depends": [
        # mail.alias.mixin (the router's own inbound address), chatter and
        # activities on routed documents
        "mail",
        # with_delay(): classification runs in the background so neither the
        # mail gateway nor a printer upload waits on TypeSafe
        "queue_job",
        # edi.exchange.type.import_template_id, the html/plaintext
        # extraction modes and the generic template processor - and, through
        # it, edi_core_oca and pypdf text extraction
        "import_from_email",
    ],
    "external_dependencies": {"python": ["typesafe_sdk", "pypdf"]},
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/edi_import_router_views.xml",
        "views/edi_import_router_document_views.xml",
        "views/menus.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
}
