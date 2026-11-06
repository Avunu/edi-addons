---
title: "Avunu EDI addons"
description:
  "These modules form a document import pipeline: they extend the OCA
  base_import_pdf_by_template module from OCA/edi so that a PDF, an email body or a
  printed document can be turned into an Odoo record by a template of patterns, with a
  live preview while you write them."
---

These modules form a document import pipeline: they extend the OCA
`base_import_pdf_by_template` module from [OCA/edi](https://github.com/OCA/edi) so that
a PDF, an email body or a printed document can be turned into an Odoo record by a
template of patterns, with a live preview while you write them. Emailed and printed
documents come in through the EDI framework of
[OCA/edi-framework](https://github.com/OCA/edi-framework). They are Odoo 18.0 modules
built and maintained by [Avunu LLC](https://avunu.net) for our own client work,
published for anyone to use.

## Modules

### Document import pipeline

Every other module here depends on `base_import_pdf_by_template_engine`, directly or
through another module. `import_from_email` files each email under the EDI exchange type
its alias names; `edi_import_router` takes emailed and printed documents into one inbox
and lets TypeSafe pick the type.

| Module                                                                        | What it does                                                                                                                                                     | Licence           |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| [`base_import_pdf_by_template_engine`](base_import_pdf_by_template_engine.md) | Two small extension points on the base module so other pattern engines and tooling can plug in without copying its methods; also fixes two table-extraction bugs | AGPL-3.0-or-later |
| [`import_preview`](import_preview.md)                                         | A persistent sample document per template and a live preview of what each line's pattern matches, right in the line dialog                                       | AGPL-3.0-or-later |
| [`import_via_xberg`](import_via_xberg.md)                                     | An `xberg` extraction mode for structured (JSON) document parsing, plus optional JSONPath narrowing on template lines                                            | AGPL-3.0-or-later |
| [`import_create_missing`](import_create_missing.md)                           | Creates the linked document on the fly when a line's search finds nothing, filled from fixed values or from the same pattern matching the line uses              | AGPL-3.0-or-later |
| [`import_create_missing_xberg`](import_create_missing_xberg.md)               | JSONPath narrowing for `import_create_missing` values on `xberg` templates; installs itself when both of its dependencies are present                            | AGPL-3.0-or-later |
| [`import_from_email`](import_from_email.md)                                   | Plain text and HTML extraction modes, a `mail.alias` entry point onto `edi.exchange.record`, and a generic template-driven EDI input processor                   | AGPL-3.0-or-later |
| [`edi_import_router`](edi_import_router.md)                                   | One inbox for emailed and printed documents: TypeSafe picks the EDI exchange type, and so the import template, for each one                                      | AGPL-3.0-or-later |

### Purchase orders

| Module                      | What it does                                                                                                                                                            | Licence           |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `edi_purchase_order_import` | Confirms a purchase order as soon as `import_from_email`'s template processor creates it from an inbound document, and notifies a group chosen in the Purchase settings | AGPL-3.0-or-later |

Each module's README explains why it exists and how it works.

## Branches

`develop` is the default branch and the one pull requests go to. Its code targets Odoo
18.0, the series named in `.odoo-series`. `18.0` follows `develop` automatically (a
workflow fast-forwards it after every push) and is the branch to install or pin. When a
newer Odoo series is maintained, it gets its own branch (`19.0`, …) and changes flow up
to it from `develop`.

## Install

Requires Odoo 18.0 and a PostgreSQL database. Pick the module or modules you want; each
pulls in the modules it depends on (see below), and those must be on your `addons_path`
first.

With a plain Odoo checkout, clone this repository on its `18.0` branch and add it to the
addons path:

```sh
git clone --branch 18.0 https://github.com/Avunu/edi-addons.git
odoo-bin --addons-path=odoo/addons,/path/to/edi-addons,<your other addons paths> \
  -d <database> -i <module> --stop-after-init
```

With [odoo-nix](https://github.com/Avunu/odoo-nix), add the repository from the dev
shell. `odoo module add` accepts an `owner/repo` and a branch, adds it as a submodule,
and the addons path is regenerated from the folders present (run `direnv reload`
afterwards):

```sh
odoo module add Avunu/edi-addons 18.0
```

## Dependencies

Each module's `__manifest__.py` is the source of truth. Besides Odoo core modules
(`mail`, and `purchase` for `edi_purchase_order_import`), the modules depend on the
following. The OCA repositories listed are the 18.0 branches; clone the ones your chosen
modules need, along with whatever those modules need in turn (their own manifests list
it).

| Module                               | Needs from OCA or others                                                                                                                                                                                  | Python packages         |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| `base_import_pdf_by_template_engine` | `base_import_pdf_by_template` ([OCA/edi](https://github.com/OCA/edi))                                                                                                                                     | none                    |
| `import_preview`                     | `base_import_pdf_by_template_engine` (this repository)                                                                                                                                                    | none                    |
| `import_via_xberg`                   | `base_import_pdf_by_template_engine` (this repository)                                                                                                                                                    | `jsonpath_ng`, `xberg`  |
| `import_create_missing`              | `base_import_pdf_by_template_engine` (this repository)                                                                                                                                                    | none                    |
| `import_create_missing_xberg`        | `import_create_missing` and `import_via_xberg` (this repository)                                                                                                                                          | none                    |
| `import_from_email`                  | `base_import_pdf_by_template` ([OCA/edi](https://github.com/OCA/edi)), `edi_core_oca` ([OCA/edi-framework](https://github.com/OCA/edi-framework)), `base_import_pdf_by_template_engine` (this repository) | none                    |
| `edi_import_router`                  | `queue_job` ([OCA/queue](https://github.com/OCA/queue)), `import_from_email` (this repository)                                                                                                            | `typesafe_sdk`, `pypdf` |
| `edi_purchase_order_import`          | `import_from_email` (this repository)                                                                                                                                                                     | none                    |

`xberg` ships prebuilt wheels for Linux and macOS (x86_64 and arm64), so installing it
needs no Rust toolchain. `edi_import_router` also needs a TypeSafe API key, entered in
Settings or set as `TYPESAFE_API_KEY`; see its README.

## Development

The repository carries its own development environment, built by
[odoo-nix](https://github.com/Avunu/odoo-nix) in addons mode. OCB and the repositories
these modules depend on are flake inputs pinned in `flake.lock`, and the Python
environment is locked in `nix/`. You need Nix with flakes, and optionally direnv.

```sh
git clone https://github.com/Avunu/edi-addons.git && cd edi-addons
direnv allow                  # or: nix develop --no-pure-eval
devenv up                     # PostgreSQL, Odoo and Mailpit
odoo db provision             # a database with every module here installed
odoo test base_import_pdf_by_template_engine
```

After `nix flake update`, or when a module gains a `depends` or a Python requirement,
run `odoo project relock` and commit `flake.lock` and `nix/`. A new dependency on
another repository also needs its input and an `externalSources` entry in `flake.nix`.
See odoo-nix's
[A repository of addons](https://github.com/Avunu/odoo-nix/blob/main/docs/scaffolding/addons-repository.md).

## Tests

Odoo runs a module's tests when you install or update it with `--test-enable`. Select a
module's tests with a `--test-tags` filter and use a throwaway database:

```sh
odoo-bin -c odoo.conf -d <testdb> -i <module> \
  --test-enable --test-tags /<module> --stop-after-init
```

Notes from the module READMEs:

- `import_preview`'s load-bearing test is
  `test_preview_updates_from_unsaved_parent_sample_data`: it drives the line dialog
  through `odoo.tests.Form` with an unsaved parent template and checks that the preview
  follows the template's in-memory sample data.
- `import_via_xberg` runs a real extraction against a committed PDF fixture,
  `tests/data/sample_parts_invoice.pdf`, through the `xberg` library; there is no CLI or
  `PATH` dependency.

Some tests are skipped unless an optional module is installed in the test database: one
`base_import_pdf_by_template_engine` test class needs `purchase`, and a few
`import_create_missing` tests need `product`. `edi_purchase_order_import` has no
automated tests.

## Licence

Every module is licensed under the
[GNU Affero General Public License v3.0 or later](https://github.com/Avunu/edi-addons/blob/18.0/LICENSE),
as its `__manifest__.py` also states (`AGPL-3`, Odoo's identifier for version 3).

`import_preview` vendors `microlighter` 2.1.0 (MIT) under `static/lib/microlighter/`. It
keeps its own licence, whose text sits next to the vendored files.

## Provenance

`base_import_pdf_by_template_engine`, `import_preview`, `import_via_xberg`,
`import_create_missing`, `import_create_missing_xberg`, `import_from_email` and
`edi_import_router` moved here, with their history, from
[Avunu/avunu-odoo-addons](https://github.com/Avunu/avunu-odoo-addons) in November 2026,
when Avunu split that repository into one repository per OCA area.
`edi_purchase_order_import` was first developed in a private Avunu project and imported
here.
