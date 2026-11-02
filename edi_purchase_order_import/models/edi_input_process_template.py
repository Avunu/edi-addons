# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import models


class EdiInputProcessTemplate(models.AbstractModel):
    """After the generic template import creates a record, give purchase
    orders their own follow-up: confirm the RFQ and let someone know.

    `edi.input.process.template.process()` (import_from_email) is
    deliberately model-agnostic - it doesn't know or care what kind of
    record its template produces. That's still the right default for
    "just create the record", but a purchase order specifically shouldn't
    sit around as an unconfirmed RFQ waiting for someone to notice it: an
    EDI/email order confirmation already represents a done deal with the
    vendor, so it should land as a confirmed Purchase Order, and someone
    should be told it arrived.
    """

    _inherit = "edi.input.process.template"

    def process(self, exchange_record):
        result = super().process(exchange_record)
        record = exchange_record.record
        if record and record._name == "purchase.order":
            record._edi_confirm_and_notify()
        return result
