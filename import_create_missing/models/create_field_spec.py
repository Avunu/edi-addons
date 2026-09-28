# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Required-field discovery for a line's **New Document Values** table.

Pure(ish) helpers, deliberately kept out of the model file: they answer
"what does creating a record of this model actually *need*, and what would
Odoo itself put there by default" without knowing anything about
`base.import.pdf.template.line.create.value` rows. The model layer turns
the answers into rows; these functions never touch one.
"""
from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from odoo.fields import Field
from odoo.models import BaseModel
from odoo.tools import clean_context

#: The kinds of typed `fixed_value_*` column a `Fixed` row can store its
#: value in. Deliberately coarser than `ir.model.fields.ttype`: `text`,
#: `html` and `json` all live in the same Char column, and `monetary` is
#: just a float.
FixedValueKind = Literal[
    "char", "boolean", "integer", "float", "selection", "date", "datetime", "record"
]

#: `FixedValueKind` -> the field on
#: `base.import.pdf.template.line.create.value` that holds it. The single
#: source of truth for the whole typed-value mechanism: the `Fixed` value
#: getter, the summary, the `@api.depends` of every value-sensitive
#: compute, and the legacy-value migration all read this mapping rather
#: than repeating the list of columns.
FIXED_VALUE_FIELD: Final[Mapping[FixedValueKind, str]] = {
    "char": "fixed_value",
    "boolean": "fixed_value_boolean",
    "integer": "fixed_value_integer",
    "float": "fixed_value_float",
    "selection": "fixed_value_selection_id",
    "date": "fixed_value_date",
    "datetime": "fixed_value_datetime",
    "record": "fixed_value_ref",
}

#: `ir.model.fields.ttype` -> `FixedValueKind`. A ttype missing from this
#: mapping (`one2many`, `many2many`, `binary`, ...) has no `Fixed` input at
#: all - see `fixed_value_kind()`.
_TTYPE_KIND: Final[Mapping[str, FixedValueKind]] = {
    "char": "char",
    "text": "char",
    "html": "char",
    "json": "char",
    "boolean": "boolean",
    "integer": "integer",
    "float": "float",
    "monetary": "float",
    "selection": "selection",
    "date": "date",
    "datetime": "datetime",
    "many2one": "record",
    "reference": "record",
}


def fixed_value_kind(
    ttype: str | bool, has_selection_options: bool = True
) -> FixedValueKind | None:
    """Which typed `Fixed` input a field of `ttype` uses, or `None` when it
    has none (a one2many is filled from its own nested Row Values table
    instead, and there is no sensible literal input for many2many/binary).

    `has_selection_options` is `False` for a *dynamic* selection - one
    whose options are computed at runtime, which Odoo therefore never
    reflects into `ir.model.fields.selection` (see
    `ir.model.fields.selection._reflect_selections()`, which only reflects
    a field whose `selection` is a plain list). There is no dropdown to
    offer for one of those, so it falls back to a free-text value.
    """
    if not ttype:
        return None
    if ttype == "selection" and not has_selection_options:
        return "char"
    return _TTYPE_KIND.get(ttype)


@dataclass(frozen=True, slots=True)
class CreateFieldSpec:
    """One field a new document genuinely requires, already resolved to
    the `ir.model.fields` record a New Document Values row can point at."""

    #: `ir.model.fields` id - of the model that *defines* the field, which
    #: for a delegated (`_inherits`) field is the parent model, never the
    #: delegating one. That is exactly what a row's `field_id` domain
    #: (`candidate_model_ids`) accepts.
    field_id: int
    name: str
    label: str
    ttype: str
    comodel: str | None
    #: Whether Odoo itself would fill this field in on `create()` - an
    #: `ir.default`, a Python `default=`, or a parent model's default. A
    #: required field with a default is never *missing*: leaving its row
    #: empty simply lets Odoo apply the default.
    has_default: bool
    #: The default value itself, in `create()`/write format (an id for a
    #: many2one, the key for a selection, ...). Meaningless unless
    #: `has_default`.
    default: Any = None


#: Field types whose falsy default (`False`, `0`, `0.0`) is a genuine
#: value rather than `default_get()`'s way of saying "nothing here".
_FALSY_DEFAULT_IS_REAL: Final[frozenset[str]] = frozenset(
    {"boolean", "integer", "float", "monetary"}
)


def _delegation_link_names(model: BaseModel) -> frozenset[str]:
    """The `_inherits` link fields on `model` (e.g. `product.product`'s
    `product_tmpl_id`). Always required, but never something a user should
    fill in: `create()` builds the parent record from the delegated values
    in the very same call."""
    return frozenset(model._inherits.values())


def _required_fields(
    model: BaseModel, exclude: Collection[str] = ()
) -> Iterator[tuple[str, Field]]:
    """`(name on model, defining field)` for every field `create()` would
    genuinely reject the record without."""
    env = model.env
    excluded = set(exclude) | _delegation_link_names(model) | {"id"}
    for name, field in model._fields.items():
        if name in excluded:
            continue
        # For a delegated field, everything that matters (required, store,
        # compute, ...) is a property of the field on the model that
        # DEFINES it - the delegating model only holds a related proxy.
        base = field.base_field
        if not base.required or not base.store:
            continue
        if base.type in ("one2many", "many2many"):
            # Not backed by a column; `required` on one of these (e.g.
            # `product.template.product_variant_ids`) is a UI hint the ORM
            # never enforces on create, and the record fills it itself.
            continue
        if base.compute:
            # It fills itself - `uom_po_id`, `service_tracking`, and every
            # `related=` field (which is implemented as a compute). Adding
            # a row for one would fight the compute, not help it.
            continue
        if base.name in _delegation_link_names(env[base.model_name]):
            continue
        yield name, base


def required_field_names(
    model: BaseModel, exclude: Collection[str] = ()
) -> frozenset[str]:
    """Just the names - the cheap half of `required_field_specs()`, with no
    `default_get()` behind it, for the per-row `is_required` flag."""
    return frozenset(name for name, _field in _required_fields(model, exclude))


def required_field_specs(
    model: BaseModel, *, exclude: Collection[str] = ()
) -> list[CreateFieldSpec]:
    """Every field a new `model` record requires, with Odoo's own default
    for it resolved in a single `default_get()` call.

    `exclude` drops fields that are already handled elsewhere - the line's
    search field (pre-filled with the value that missed, see
    `base.import.pdf.template.line._create_missing_prefill_field_name()`)
    and, for a nested one2many, that one2many's own inverse field.

    Sorted so the rows that still need the user's attention (no default,
    nothing to fall back on) come first.
    """
    env = model.env
    fields_by_name = dict(_required_fields(model, exclude))
    if not fields_by_name:
        return []
    # One call for the whole set - `default_get()` already covers
    # ir.default, `default=` and the delegated parents' own defaults. The
    # context is cleaned because this runs from a view whose context is
    # full of `default_line_id`-style keys meant for OUR records, which
    # would otherwise be mistaken for defaults of the target model.
    defaults = model.with_context(clean_context(env.context)).default_get(
        list(fields_by_name)
    )
    specs: list[CreateFieldSpec] = []
    ir_model_fields = env["ir.model.fields"]
    for name, field in fields_by_name.items():
        field_record = ir_model_fields._get(field.model_name, field.name)
        if not field_record:
            # Not reflected (a field of a model whose module is being
            # installed right now) - nothing a row could point at.
            continue
        default = defaults.get(name)
        has_default = name in defaults
        if field.type not in _FALSY_DEFAULT_IS_REAL:
            # `default_get()` happily returns a falsy value for a field it
            # has no real default for, so for most types "empty" has to be
            # read as "no default". Not for the scalar types below, where
            # False/0/0.0 is a perfectly ordinary default that Odoo really
            # will apply - `product.supplierinfo.price` defaults to 0.0,
            # and treating that as "missing" would nag about a field the
            # user never has to touch.
            has_default = has_default and bool(default)
        specs.append(
            CreateFieldSpec(
                field_id=field_record.id,
                name=name,
                label=field_record.field_description or name,
                ttype=field.type,
                comodel=getattr(field, "comodel_name", None),
                has_default=has_default,
                default=default,
            )
        )
    specs.sort(key=lambda spec: (spec.has_default, spec.label))
    return specs
