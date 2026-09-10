# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Import From Email",
    "summary": "Bridge inbound email into base_import_pdf_by_template and the "
    "EDI framework: extraction modes for plain text/HTML sources, a "
    "mail.alias entry point onto edi.exchange.record, and a generic "
    "template-driven input processor.",
    "version": "18.0.1.0.0",
    "category": "Technical",
    "author": "Avunu LLC",
    "website": "https://avu.nu",
    "license": "AGPL-3",
    "depends": [
        "base_import_pdf_by_template",
        # Not used directly - this module's templates are plain regex
        # against flat text, exactly like a pypdf template, so there is no
        # engine seam here to call. Depended on anyway so the engine's two
        # `_get_table_info_data()` bug fixes (an IndexError when no "lines"
        # child line has a pattern yet, and a "lines" column shorter than
        # its siblings silently shifting every later column of that row)
        # always apply wherever this module is installed - a template with
        # a repeating item table (a NAPA order confirmation has one - see
        # tests/data/napa_order_confirmation.txt) hits exactly this path.
        "base_import_pdf_by_template_engine",
        "edi_core_oca",
    ],
    "data": [
        "views/edi_exchange_type_views.xml",
    ],
    "installable": True,
}
