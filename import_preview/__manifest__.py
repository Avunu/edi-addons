# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Import Preview",
    "summary": "A persistent reference sample per base_import_pdf_by_template "
    "template, and a live match preview in the line editor - see what a "
    "pattern actually extracts while you write it.",
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
    "assets": {
        "web.assets_backend": [
            # Vendored (microlighter 2.1.0, MIT) - a genuine ES module.
            # Deliberately NOT listed here: Odoo's asset bundler has no
            # concept of a real `<script type="module">` file, so a static
            # `web.assets_backend` entry would concatenate its `export`
            # statement as plain script text - a hard SyntaxError that took
            # the whole bundle down with it the first time this was tried.
            # `json_highlight_field.js` loads it itself, at runtime, via a
            # dynamic `import()` expression (which - unlike a static import
            # statement - Odoo's bundler/transpiler leaves alone, and which
            # the browser's own native module loader then correctly
            # resolves, completely bypassing Odoo's bundler); see the long
            # comment there for the full explanation. Odoo still serves the
            # file at its ordinary static URL regardless of this list.
            "import_preview/static/lib/microlighter/themes/github.css",
            "import_preview/static/src/json_highlight_field/json_highlight_field.js",
            "import_preview/static/src/json_highlight_field/json_highlight_field.xml",
            "import_preview/static/src/json_highlight_field/json_highlight_field.scss",
        ],
    },
    "installable": True,
}
