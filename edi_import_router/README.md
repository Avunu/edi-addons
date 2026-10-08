# EDI Import Router

One inbox for documents that reach Odoo by email or by printer. TypeSafe decides which `edi.exchange.type` each one is, and the document is filed under it like any other EDI input.

## Why

Every vendor document used to need its own route: one `mail.alias` per vendor on `edi.exchange.record` (so one Gmail forwarding rule per vendor), and no way at all in for a quote that only exists on a web page. The routing decision is really "which exchange type is this?", because that type already pins the `base.import.pdf.template` and the processor. This module makes that decision once, for both channels.

## What it adds

-   **`edi.import.router`**: a named intake with an optional email alias, a confidence threshold, a responsible user and a list of targets.
-   **`edi.import.router.target`**: an input `edi.exchange.type` (and its backend) with a description of what tells that document apart. The descriptions are the choices TypeSafe picks between. A target can be limited to email or printed documents; whatever the setting, a document is only offered to a type whose template can read it (an email body needs an `html`/`plaintext` template, a PDF a PDF template).
-   **`edi.import.router.document`**: one emailed or printed document with its chatter, state (`pending`, `routed`, `review`, `ignored`, `error`), TypeSafe's confidence and probabilities, and the exchange record it became.
-   A background job (`queue_job`) that asks one TypeSafe `Choice` question and acts on the answer: a confident match is filed with `backend.create_record()` (the same call `import_from_email` makes), `none` is ignored, and anything uncertain or failed waits for review with an activity for the responsible user. A document waiting for review (or wrongly ignored) shows every target of the router with TypeSafe's probability for it; **Route here** on a row files the document under that type, and **Ignore** on the "None of these" row discards it. **Re-classify** asks TypeSafe again after you fix a description.
-   **Honest about what it asked.** A target is only offered to TypeSafe if its template can read the document (`html`/`plaintext` read an email body, `pypdf` a PDF, `xberg` either). Targets that could not be offered are listed in the document's chatter and marked in the choices list, and while any exist a TypeSafe answer of "none" goes to review instead of being ignored, because TypeSafe was never asked about them. The target list's **Reads** column shows what each type's template can read.
-   `ignore_threshold` (default 98%): "none" below this goes to review rather than being ignored. A wrongly ignored order costs far more than an extra review item.
-   For forwarded email, TypeSafe is also given `original from`, read from the forwarded-message header.

## Ways in

-   **Email:** forward to the router's alias. `message_new` creates a document holding the raw HTML body. `mail_cloudflare` must add the envelope recipient as `Delivered-To` even when the message already carries the forwarder's, or a Gmail auto-forward never matches the alias.
-   **Printer:** ERP Printer uploads a PDF `ir.attachment` attached to the router (`res_model = edi.import.router`, `res_id` = the router). A user in *Import router: printer upload* may do exactly that and cannot edit the router. Identical files are ignored, so an outbox retry never files twice.

## Configuration

1.  Settings: enter the TypeSafe API key (or set `TYPESAFE_API_KEY`).
2.  Create the input exchange types with their templates (`import_from_email` explains how).
3.  Import Routers: create a router, give it an alias for email, and add one target per exchange type with a description.
4.  Printer: create an Odoo user in the *printer upload* group with an API key, then on the ERP Printer profile set Backend `OdooJsonRpc` (Odoo 18), Odoo model `ir.attachment`, Attach to model `edi.import.router` and Attach to record ID = the router's id (shown on the router form).

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i edi_import_router \
  --test-enable --test-tags /edi_import_router --stop-after-init
```
