# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import enum

from odoo.tests.common import BaseCase

from odoo.addons.import_via_xberg.wizards.wizard_base_import_pdf_mixin import (
    _TO_JSONABLE_MAX_DEPTH,
    _to_jsonable,
)


class _Color(enum.Enum):
    RED = 1


class _Node:
    """A minimal stand-in for an xberg result object: a plain Python class
    exposing data through attributes, with the same shape `_to_jsonable()`
    has to walk (public getters, a callable to be filtered out)."""

    def __init__(self, value=None, child=None):
        self.value = value
        self.child = child

    def a_method(self):  # must be excluded: callable, not data
        return "should not appear"


class _JsonReprObj:
    """Stands in for an xberg result class wrapping a Rust tagged union
    with data (e.g. `FormatMetadata`, whose `link_type` field is one of
    these): its `__repr__` already IS a correct, compact JSON
    serialisation of the active variant (the Rust `Debug` impl bridged
    straight into Python)."""

    def __repr__(self):
        return '{"link_type": "email", "href": "mailto:x"}'


class _PlainStructObj:
    """Stands in for an xberg result class that is a plain struct, not a
    tagged union (e.g. `Table`, `Metadata`, `ExtractedDocument`): no JSON
    repr, just the pyo3 default `<builtins.X object at 0x...>` - must fall
    through to the attribute walk."""

    def __init__(self, value=None):
        self.value = value

    def __repr__(self):
        return f"<builtins.{type(self).__name__} object at 0x0>"


class TestToJsonable(BaseCase):
    """`BaseCase` (not plain `unittest.TestCase`) is required here even
    though these tests never touch a database: Odoo's tag_selector skips
    any test lacking a `test_tags` attribute whenever `--test-tags`
    filtering is active (`tag_selector.check()`), and only `BaseCase`'s
    metaclass assigns that automatically. A plain `unittest.TestCase`
    subclass under `odoo.addons.*` silently never runs under the normal
    `-i ... --test-enable --test-tags /module` invocation - not even a
    warning, just zero tests collected from that class.
    """

    def test_primitives_pass_through(self):
        self.assertEqual(_to_jsonable("x"), "x")
        self.assertEqual(_to_jsonable(1), 1)
        self.assertEqual(_to_jsonable(1.5), 1.5)
        self.assertEqual(_to_jsonable(True), True)
        self.assertIsNone(_to_jsonable(None))

    def test_bytes_are_dropped(self):
        self.assertIsNone(_to_jsonable(b"raw image data"))

    def test_enum_becomes_its_name(self):
        self.assertEqual(_to_jsonable(_Color.RED), "RED")

    def test_lists_dicts_and_nested_objects(self):
        node = _Node(value=[1, 2, {"k": "v"}], child=_Node(value="leaf"))
        result = _to_jsonable(node)
        self.assertEqual(result["value"], [1, 2, {"k": "v"}])
        self.assertEqual(result["child"]["value"], "leaf")
        self.assertNotIn("a_method", result)

    def test_shared_reference_does_not_infinite_loop(self):
        shared = _Node(value="shared")
        node = _Node(value=shared, child=shared)
        result = _to_jsonable(node)  # must return, not hang or raise
        # Exactly one of the two references to `shared` gets expanded (the
        # first one `_to_jsonable` walks - which attribute that is depends
        # on `dir()`'s ordering, an implementation detail not worth pinning
        # down); the other is cut off as an already-visited object rather
        # than re-walked or - the failure mode this test actually guards
        # against - recursed into forever.
        expanded = [v for v in (result["child"], result["value"]) if v is not None]
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0], {"value": "shared", "child": None})

    def test_depth_cap_terminates_deep_chains(self):
        head = tail = _Node(value=0)
        for i in range(1, _TO_JSONABLE_MAX_DEPTH + 10):
            tail.child = _Node(value=i)
            tail = tail.child
        result = _to_jsonable(head)  # must terminate rather than recurse forever
        depth = 0
        node = result
        while isinstance(node, dict) and node.get("child") is not None:
            node = node["child"]
            depth += 1
        self.assertLessEqual(depth, _TO_JSONABLE_MAX_DEPTH)

    def test_prefers_json_repr_over_attribute_walk(self):
        """Regression test for a real bug: `xberg`'s `FormatMetadata.links[
        ].link_type` is a Rust tagged union whose `__repr__` is already
        correct JSON (`"email"`, `"anchor"`, ...). Walking its `dir()`
        instead - the pre-fix behaviour - reflected over its raw variant
        accessors and reconstructed a bogus, self-referential
        `{"ANCHOR": null, "EMAIL": {...}, ...}` tree that kept re-nesting
        itself out to `_TO_JSONABLE_MAX_DEPTH`, turning one real-world
        document's ~210KB `--format json` equivalent into 17MB of almost
        entirely null padding. A JSON `__repr__`, when present, must
        always be trusted over the generic walk.
        """
        self.assertEqual(
            _to_jsonable(_JsonReprObj()),
            {"link_type": "email", "href": "mailto:x"},
        )

    def test_falls_back_to_attribute_walk_without_json_repr(self):
        result = _to_jsonable(_PlainStructObj(value="leaf"))
        self.assertEqual(result, {"value": "leaf"})

    def test_json_repr_object_nested_inside_plain_struct(self):
        # The common real shape: `ExtractedDocument.metadata.format` (a
        # plain struct, default repr) has a `.links` list of tagged-union
        # link records (JSON repr) - both paths have to compose correctly.
        node = _PlainStructObj(value=_JsonReprObj())
        result = _to_jsonable(node)
        self.assertEqual(result["value"], {"link_type": "email", "href": "mailto:x"})
