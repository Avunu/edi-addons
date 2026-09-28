# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Import Create Missing",
    "summary": "Create the linked document on the fly when a "
    "base_import_pdf_by_template line's search misses, filling it from "
    "fixed values or the same pattern matching the line itself uses.",
    "version": "18.0.1.1.0",
    "category": "Technical",
    "author": "Avunu LLC",
    "website": "https://avu.nu",
    "license": "AGPL-3",
    "depends": [
        "base_import_pdf_by_template_engine",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/base_import_pdf_template_line_create_value_views.xml",
        "views/base_import_pdf_template_line_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "import_create_missing/static/src/required_values_warning.js",
        ],
    },
    "installable": True,
}
