# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Move pre-1.1.0 `Fixed` values into their typed columns.

The work itself lives on the model
(`base.import.pdf.template.line.create.value._migrate_legacy_fixed_value()`)
rather than here, so it can be exercised by the test suite - a migration
script is unreachable from a test run.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["base.import.pdf.template.line.create.value"]._migrate_legacy_fixed_value()
