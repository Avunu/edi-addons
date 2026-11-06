# EDI Purchase Order Import

Confirms a purchase order as soon as an inbound EDI or email document creates it, and
tells a chosen group that it arrived.

## Why

`import_from_email`'s processor (`edi.input.process.template`) is deliberately
model-agnostic: it creates whatever record its template targets and stops there. For a
purchase order that leaves an unconfirmed RFQ waiting for someone to notice it, but an
inbound order confirmation already represents a done deal with the vendor.

## What it adds

- **`edi.input.process.template.process()`** is extended: when the record an exchange
  creates is a `purchase.order`, it calls `_edi_confirm_and_notify()` on it. Any other
  kind of record is left as the generic processor made it.
- **`purchase.order._edi_confirm_and_notify()`** confirms the order if it is still a
  draft, then posts a message on it that notifies every user of the chosen group, so it
  appears in their inbox.
- **Notify Group on Imported Purchase Orders**, a setting in Settings > Purchase, kept
  in the `edi_purchase_order_import.notify_group_id` system parameter.

## Configuration

Installing the module sets the group to Purchase: Administrator, which is also the
fallback when the parameter is empty or names a group that no longer exists. Exchange
types and templates are configured as `import_from_email` describes; this module needs
nothing further.

## Tests

This module has no automated tests.
