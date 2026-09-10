# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Import via Xberg",
    "summary": "Extraction mode backed by the `xberg` Python library for "
    "structured (JSON) document parsing, and JSONPath pattern matching on "
    "base_import_pdf_by_template template lines for that mode.",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "author": "Avunu LLC",
    "website": "https://avu.nu",
    "license": "AGPL-3",
    "depends": [
        "base_import_pdf_by_template_engine",
    ],
    "data": [
        "views/base_import_pdf_template_views.xml",
        "views/base_import_pdf_template_line_views.xml",
    ],
    "external_dependencies": {
        "python": ["jsonpath_ng", "xberg"],
    },
    "installable": True,
}
