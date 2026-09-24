# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Import Create Missing - Xberg Bridge",
    "summary": "JSONPath narrowing (import_via_xberg) for "
    "import_create_missing's New Document Values, on templates using the "
    "xberg extraction mode.",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "author": "Avunu LLC",
    "website": "https://avu.nu",
    "license": "AGPL-3",
    "depends": [
        "import_create_missing",
        "import_via_xberg",
    ],
    "data": [
        "views/base_import_pdf_template_line_views.xml",
    ],
    "auto_install": True,
    "installable": True,
}
