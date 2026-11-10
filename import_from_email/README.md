# Base Import From Email

Three pieces that together let an inbound email drive `base_import_pdf_by_template`
through the EDI framework's exchange-record pipeline instead of only a manually-uploaded
PDF — for as many different senders and target document types as you configure, not just
one:

1. Two `extraction_mode` options on `base.import.pdf.template` — `plaintext` and `html`
   — alongside the `pypdf` mode that ships with `base_import_pdf_by_template`. A
   template using either mode is matched and processed exactly like a PDF-based one;
   only the first step (turning the source file into text) is different.
2. A `mail.alias` entry point onto `edi.exchange.record` (from `edi_core_oca`), so an
   inbound email creates a tracked, retryable EDI exchange record instead of a bespoke
   `mail.thread` hook.
3. A generic EDI input processor (`edi.input.process.template`) that turns an exchange
   record into an Odoo record using whichever `base.import.pdf.template` its exchange
   type points at. Add a new `edi.exchange.type` + `base.import.pdf.template` pair for
   every new sender/document combination; no new code.

## Why

`base_import_pdf_by_template`'s regex-based field/table matching
(`_get_field_header_values`, `_get_table_info`) already works on a plain text string —
`pypdf` is only there to get from a PDF binary to that string. Some sources never
produce a PDF at all. Parts-supplier order confirmation emails, for example, only exist
as an email body (plain text and HTML alternative parts) — no PDF attachment. This
module lets a template be built directly against that text, without inventing a separate
import pipeline per document model.

The module is deliberately generic: it only adds extraction modes to the existing
framework. It doesn't know about email, purchase orders, or any other specific model —
any module that materializes a plain text or HTML body as an `ir.attachment` (mimetype
`text/plain` or `text/html`) can hand it to `wizard.base.import.pdf.upload` and get the
same auto-detect + template-line processing that PDF attachments get today.

## What it adds

- `extraction_mode = "plaintext"`: reads the source bytes back as UTF-8 text, no
  transformation.
- `extraction_mode = "html"`: same, then runs it through Odoo's `html2plaintext` to
  strip markup before the template's patterns see it.

Both live in `wizards/wizard_base_import_pdf_mixin.py`, following the same
`_pdf_text_extraction_<mode>` naming the base module uses for `pypdf`, so
`simple_pdf_text_extraction()`'s dynamic dispatch and `_parse_pdf_grouped()`'s
try-every-mode auto-detection keep working unmodified.

This module also depends on `base_import_pdf_by_template_engine` (see that module's
README), even though nothing here calls the seams it adds - a `plaintext`/`html`
template's lines are always plain regex against flat text, matched exactly like a
`pypdf` template's. The dependency exists so the engine's two `_get_table_info_data()`
bug fixes (an `IndexError` when no "lines" child line has a pattern yet, and a "lines"
column with fewer matches than its siblings silently shifting every later column of that
row instead of leaving a blank cell) always apply here too. That second bug is not
theoretical for this module: a parts-supplier order confirmation has a repeating item
table (see `tests/data/parts_order_confirmation.txt`), and any "lines" template built
against it - or a future sender with similar structure - would hit exactly that path the
moment one item's column doesn't match as many times as another's.

## Routing email into an exchange record

`edi.exchange.record` already inherits `mail.thread` (from `edi_core_oca`), so a
`mail.alias` can point directly at it — `models/edi_exchange_record.py` overrides
`message_new()` to make that alias useful: it stores the raw message body as the
exchange's `exchange_file` and hands off to `edi.backend.create_record()`, which
resolves the right `edi.exchange.type` and (per that type's `quick_exec` setting) can
trigger processing immediately.

The alias only needs two defaults, resolved via its `alias_defaults`:

- `backend_id` — which EDI backend the message belongs to.
- `type_code` — which `edi.exchange.type.code` to file it under.

Both are required; a message routed here without them raises rather than creating a
record `type_id` can't actually be set on. The body is kept as raw HTML (no conversion
at intake) — interpreting it is the extraction template's job, using the `html` mode
added above.

The record is created with `edi_exchange_state = "input_received"` straight away: the
whole document already arrived in the email, so there is no separate "receive"
round-trip to wait for. Skipping this would leave a `quick_exec` type stuck at `"new"`
forever — the receive/process cron domains only look for `"input_pending"` and
`"input_received"` respectively (see
`edi_backend._input_pending_records_domain`/`_input_pending_process_records_domain`),
and plain `create()` on `edi.exchange.record` does not infer this transition on its own.

The email's own `Message-Id` and `Subject` are also stored on the exchange record
(`inbound_message_id`, `inbound_subject`). This is deliberate: with `quick_exec` the
record is processed *inside* `create_record()`, i.e. before Odoo's mail gateway has posted
the inbound `mail.message` on the exchange record, so a processor that wants to answer the
email in the same conversation thread (see `edi_purchase_order_import`) cannot look it up
on the chatter at that point.

### Where a reply goes (`inbound_reply_to`)

In the typical set-up a vendor emails a shop mailbox (Gmail, say) and a forwarding rule
passes the email on to the Odoo mail alias. A reply to it must go back to that **shop
mailbox**, never to the vendor who wrote the email. `message_new()` therefore computes the
addresses to reply to and stores them, comma separated and normalized, in
`inbound_reply_to` (empty when nothing could be determined):

1. The mailbox that **forwarded** the email is named by `X-Forwarded-For` (Gmail's
   forwarding rules add it): when it names someone, that is the answer. Otherwise use the
   addresses the email was originally addressed to — its `To` header — leaving out
   colleagues of the sender (the same domain, unless that is a public mailbox provider such
   as gmail.com). `Cc` is ignored.
2. Remove: addresses of this Odoo instance (the bounce, catchall and default-from address
   of every `mail.alias.domain`, every `mail.alias` — including the exchange alias itself —
   and the legacy `mail.catchall.*` system parameters); the Odoo-side delivery targets —
   only the **top-most** `Delivered-To` (added by the Odoo side's mail server; the ones
   below were added by the shop's own server as the email passed through the shop mailbox,
   and name that very mailbox, so they stay) and `X-Forwarded-To` (where the forwarding
   rule sends the email); the original sender (the vendor, `From`); and no-reply style
   addresses (`noreply`, `no-reply`, `donotreply`, `mailer-daemon`, `postmaster`,
   `bounce`, ...). `X-Original-To` is not used.
3. When nothing is left — the email was forwarded **by hand** to the alias, so its `To` was
   only the alias — fall back to the forwarder, i.e. the `From` address, unless that is an
   instance or no-reply address too.
4. Keep at most 5 addresses (`MAX_REPLY_ADDRESSES`): whoever can write to the alias chooses
   these headers. `edi_purchase_order_import` additionally only emails addresses it knows to
   be shop-side (see its README).

Odoo's `message_parse()` keeps neither `X-Forwarded-For` nor the separate `To` and
`Delivered-To` (they are merged in `msg_dict["to"]`), and extra keys cannot be added to
`msg_dict` (the gateway hands it to `message_post()`, which rejects unknown ones). So
`models/mail_thread.py` extends `mail.thread._message_route_process()`: when a route
targets an `edi.exchange.record` it puts the raw routing headers in the context
(`edi_inbound_headers`), where `message_new()` finds them — also when the gateway reaches
the record through `message_update()` (an email whose References collide with an earlier
exchange; it then gives no `update_vals`, so the new exchange is filed under the backend and
type of the earlier one). When `message_new()` is called without the headers, the
flattened `msg_dict["to"]` is all there is.

A vendor that writes to the alias directly (no forwarding) ends up in the fallback, as the
sender. Consumers that know the vendor must filter it out themselves; `edi_purchase_order_import`
does.

The addresses are only *stored* here; sending is up to the processor. Instance addresses
are read as sudo, because whoever feeds the gateway (alias owner, cron) may not be allowed
to read aliases; only email addresses come out of it.

## Processing an exchange record generically

`models/edi_input_process_template.py` adds `edi.input.process.template`, an
`edi.oca.handler.process` implementation that:

1. Reads `exchange_record.type_id.import_template_id` (a new field this module adds to
   `edi.exchange.type`).
2. Extracts text via that template's own `extraction_mode` (reusing
   `simple_pdf_text_extraction()` — the same dispatch the PDF wizard uses).
3. Runs the template's field/table matching and creates the record with the same
   `Form()`-based engine `wizard.base.import.pdf.upload` uses for a manual upload.
4. Links the result back to the exchange record via `_set_related_record()`.

To use it for a new sender or document type: build a `base.import.pdf.template` for that
model as usual, create an `edi.exchange.type` with **Processor** set to "EDI Input
Process: Import by Template" and **Import Template** set to that template, and point a
`mail.alias` (or any other trigger) at it with the matching `backend_id`/`type_code`.
Nothing here is written against one particular supplier, purchase orders, or any other
specific document — that's the point: the same processor model serves every exchange
type configured this way.

A document whose creation needs more than the template engine gives you out of the box —
fuzzy partner/product matching, safe updates to an existing record instead of always
creating new, dedup — should get its own dedicated processor (e.g. one built on
`purchase_order_import`) registered as that exchange type's Processor instead of this
generic one. Both kinds of processor can coexist across different exchange types on the
same backend.

### `alias_defaults` isn't a per-field form

`backend_id` and `type_code` above are not fields you'll find on `edi.exchange.record`
(`backend_id` happens to also be a real column, but that's incidental) - they're just
keys in the `mail.alias`'s `alias_defaults` **text** field, which Odoo core only
validates with `ast.literal_eval` (no check against real model fields). Set it directly
as a Python dict literal, e.g.
`{'backend_id': 3, 'type_code': 'parts_supplier_po_confirmation'}` - our `message_new()`
override is the only thing that ever reads `type_code`.

### `quick_exec` is hidden for input types in the stock view

`edi_core_oca`'s form only shows `quick_exec` when `exchange_file_auto_generate` is set,
and that field is itself only shown for `direction = "output"` - so on an input exchange
type `quick_exec` is permanently hidden in the stock view, even though
`_quick_exec_enabled()` never checks `exchange_file_auto_generate` for inputs at all.
`views/edi_exchange_type_views.xml` overrides that field's `invisible` condition so it
shows for inputs too, without touching `edi_core_oca` itself.

## Reference fixture

`tests/data/parts_order_confirmation.txt` is the plain-text body of a parts-supplier
order confirmation with the sender, customer, store, and order details replaced by
fictional values (Order # ORD-00000TESTA), and `parts_order_confirmation.html` is a
trimmed-down HTML document reproducing the same structure. Both are used only to prove
the extraction methods round-trip real-world content correctly; this module does not
itself define a template or know what any one supplier's order looks like — that belongs
in whatever module actually imports that supplier's confirmations.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i import_from_email \
  --test-enable --test-tags /import_from_email --stop-after-init
```

`tests/test_reply_addresses.py` (post-install) covers the reply-address rules above: a raw
Gmail-forwarded email and a manual forward through a real `mail.alias`, instance/no-reply/sender
exclusion, `X-Forwarded-For`, the second `Delivered-To`, colleagues of the sender, the cap, an
email colliding with an earlier exchange, and the fallbacks.
