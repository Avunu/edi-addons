# EDI Purchase Order Import

Confirms a purchase order as soon as an inbound EDI or email document creates it, and
tells a chosen group that it arrived. Also provides the one shared way to post notices
about such an order (`purchase.order._edi_post_notice()`), reused by other modules such as
`repair_purchase_order_match`.

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
  draft, then posts the confirmation notice (`_edi_post_notice()`, outstanding, with
  email).
- **`purchase.order._edi_post_notice(body, email=True, outstanding=True, **message_post_kwargs)`**
  posts a notice (see below).
- **`purchase.order._edi_clear_notices()`** marks the inbox notifications of the
  outstanding notices of the order as read, for everybody.
- **`purchase.order._edi_notice_still_needed()`**, an overridable hook (default `True`).
- **`purchase.order._edi_reply_addresses()`**, **`_edi_originating_email()`**,
  **`_edi_notify_partners()`**, helpers described below.
- **`mail.message.subtype` `edi_purchase_order_import.mt_edi_notice`**, an internal subtype
  nobody follows, and **`mail.message.edi_notice_outstanding`**, the clearable marker.
- **Notify Group on Imported Purchase Orders**, a setting in Settings > Purchase, kept
  in the `edi_purchase_order_import.notify_group_id` system parameter.

## Notices

`_edi_post_notice()` does three things, and nothing else:

1. **An internal note on the purchase order**, with the `mt_edi_notice` subtype. Nobody
   is subscribed to that subtype (it is not a default one and is hidden from the follower
   options), and it is internal, so neither the vendor, a portal follower nor any other
   follower is notified by it, and the vendor cannot read it in the portal. The author is
   OdooBot unless `author_id` is given.
2. **An inbox notification (`needaction`) for the notify group** (Settings > Purchase,
   default Purchase: Administrator). **Never an email**: the notice is posted with the
   `edi_notice_mode="inbox"` notification parameter and `purchase.order._notify_get_recipients()`
   forces every recipient that is an internal user to the `inbox` notification type, whatever
   their preference ("Handle by Emails" included), and drops anyone else (partners without
   a user, portal users). The usual inbox mechanics (notification records, bus message,
   counters) are those of Odoo. The posting user is notified too if they are in the group
   (`notify_author`), since the notice is not theirs.
3. **At most one email** (`email=True`), sent **only to the reply addresses** of the order
   (see below), as a reply to the inbound email:
   - `Subject`: `Re: <inbound subject>` (an existing `Re:` is not doubled);
   - `In-Reply-To`: the inbound email's `Message-Id`;
   - `References`: the inbound `Message-Id` first, then what the order's own thread
     contributes, then the note itself, oldest first;
   - `Message-Id`: the note's own `mail.message.message_id`;
   - links to records in the body (the order, a repair order, ...) are made absolute
     (`/odoo/<model>/<id>`), as the note's own `href="#"` links only work in the web client.

   It is built by hand (a `mail.mail` linked to the note) rather than through the
   follower-based notification, so nobody else can receive it: the vendor, followers and
   the notify group get no email from this path. (A notify-group user whose own address is
   one of the reply addresses gets it, of course, as that is where it is sent.)
   Without reply addresses nothing at all is emailed: only the note and the inbox
   notification exist. Honors `mail_notify_force_send=False` in the context (the email is
   then left in the queue) like Odoo's own notifications.

### Reply addresses

`import_from_email` stores on the exchange record the addresses a reply should go to (the
shop mailbox that forwarded the vendor's email to the Odoo alias, or the person who forwarded
it by hand: see its README). `_edi_reply_addresses()` returns them for an order, minus

- every address of the order's vendor (its commercial partner and their contacts): a vendor
  that wrote to the alias directly would otherwise end up as the "forwarder";
- every address that is not **allowed** (`_edi_reply_address_allowed()`). The stored
  addresses come from the `To` / `X-Forwarded-For` headers of the inbound email, which
  anybody who can write to the mail alias controls: a notice (the "Confirm Match" link of
  `repair_purchase_order_match` included) must not become a way to email third parties.
  Only these are emailed: the emails of internal users and of companies of the database,
  and what **Settings > Purchase > Allowed Reply Addresses** (system parameter
  `edi_purchase_order_import.reply_allowed`) lists: addresses (`orders@shop.example`) and
  domains (`@shop.example`), separated by commas, spaces or new lines. **Set it to the shop
  mailbox the forwarding rule belongs to**, or no notice is emailed (the inbox
  notification still is).

An order with no exchange record, or whose exchange has no email origin (e.g. created from
a manually uploaded PDF), has none.

### Replies to the notice

The shop's answer is posted on the order by the gateway as a discussion message, which the
vendor (a follower of the order's discussions) would be emailed. `purchase.order.message_post()`
therefore turns an email reply to a notice into an internal note (`mail.mt_note`): the
internal conversation stays internal.

If an email's References collide with an earlier exchange, the gateway files the email on
that earlier record while the new exchange creates the order. The held-back notices are
released when that email is posted, wherever it is (`_message_post_after_hook` looks the
pending exchanges up by the inbound `Message-Id`).

Because the email carries the note's `Message-Id`, and Odoo's mail gateway routes a reply to
the message with the **highest id** among those listed in its `References` or `In-Reply-To`,
a reply from the shop mailbox lands on the purchase order, not on the exchange record, and is
not bounced. With `quick_exec` the order is processed inside `message_new()`, i.e. *before*
the gateway has posted the inbound email on the exchange record, so a notice posted right
away would have the lower id and the reply would be routed to the exchange record, which
rejects it. Therefore, when an email must go out, reply addresses are known and the inbound
email is not on the chatter yet, the whole notice is held back
(`edi.exchange.record.edi_pending_notices`, a JSON queue) and posted by
`_message_post_after_hook` as soon as the inbound email is there. `_edi_post_notice()` then
returns an empty recordset. Notices that do not need that ordering (`email=False`, or no
reply address, or inbound email already posted, e.g. processing without `quick_exec`) are
posted at once. A notice whose `message_post` keyword arguments are not JSON-serializable
cannot be queued and is posted at once.

### Outstanding notices

A notice posted with `outstanding=True` (the default) is flagged
(`mail.message.edi_notice_outstanding`) as one that stops being relevant once the order has
been taken care of. `_edi_clear_notices()` then marks its inbox notifications as read for
**all** users and sends the usual `mail.message/mark_as_read` bus message, with the new
inbox counter, to each affected user, so their clients update. It is idempotent, ignores
notices that are not outstanding, and works whoever calls it (it is not the recipients).
It is quiet: no email, no new notification, and the notices stay in the chatter as history.
Modules that know when an order has been dealt with (such as `repair_purchase_order_match`,
once the order is matched) call it. The notices it clears are those of
`_edi_outstanding_notices()`, which a module extends when it also posts notices about an
order elsewhere (the match module adds its suggestion notes on repair orders).

`_edi_notice_still_needed()` (default `True`) is consulted just before posting an outstanding
notice, at the time it is really posted (so after the deferral above). When it answers
`False` the note is still posted, and still emailed if asked, **but nobody gets an inbox
notification for it** and it is not flagged outstanding: there would be nothing to clear.
Override it on `purchase.order` to return `False` once the order is already taken care of
(e.g. matched to a repair order).

## Access rights

The code runs from the mail gateway, a cron or a queue job, as whoever owns the alias or the
job, who may be a low-privilege or portal-like user. `sudo()` is used where needed and nowhere
else:

- reading the exchange record, the notify group setting and its members, the vendor's
  addresses, the emails of the users and companies and the allowed reply addresses, and, in `import_from_email`, the aliases/alias domains: only ids and email
  addresses come out of it;
- posting the note and creating its inbox notifications and `mail.mail` (an ordinary user
  cannot create those);
- `_edi_clear_notices()` writes only `is_read` on inbox notifications of the outstanding
  notices of the very orders it is called on.

The calling user's rights are not widened: these are private methods (not reachable by RPC),
and `_edi_post_notice()` returns the message in the caller's environment, so it can only be
read if the caller could read it anyway. Nothing is posted *as* the caller. The notice is
internal, so portal users and the vendor cannot read it, and it is only sent to the stored
reply addresses.

## Configuration

Installing the module sets the group to Purchase: Administrator, which is also the
fallback when the parameter is empty or names a group that no longer exists. The group is
notified in their **Odoo inbox only** (it used to be emailed according to each user's
preference). Exchange types and templates are configured as `import_from_email` describes;
this module needs nothing further.

## Tests

`tests/test_reply_to_inbound_email.py` feeds raw emails (Gmail forwarding rule headers
included) through the mail gateway and a real `mail.alias` onto an `edi.exchange.record`
(with `quick_exec`) and checks: the single email to the shop mailbox only (vendor and other
followers get none), its threading headers and `Message-Id`, the manual-forward fallback, no
reply address (nothing sent, inbox still notified), inbox-only notification of a user whose
preference is "email", routing of the shop's reply to the purchase order, deferral until the
inbound email is posted, `_edi_clear_notices()` (from an unrelated user, with the bus
counter), the `_edi_notice_still_needed()` hook, and running as a low-privilege user; the
allowed reply addresses (a vendor's colleague, 20 stranger addresses, a user's mailbox
without any setting), absolute links in the emailed copy, the shop's answer staying an
internal note, an email colliding with an earlier exchange, and the flag being the
system's.
Tagged `post_install`; run with `--test-tags /edi_purchase_order_import`.
