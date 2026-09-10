# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import json
from functools import lru_cache

from odoo import api, fields, models
from odoo.exceptions import UserError

try:
    from jsonpath_ng.ext import parse as _jsonpath_parse
except ImportError:  # pragma: no cover - external_dependencies covers this
    _jsonpath_parse = None


@lru_cache(maxsize=256)
def _compile_jsonpath(expression):
    """jsonpath-ng builds a small PLY grammar on every parse() call - always
    cache compiled expressions, since the same pattern is evaluated once per
    row/match during a real import."""
    return _jsonpath_parse(expression)


@lru_cache(maxsize=4)
def _parse_document(text):
    """Parse the xberg JSON envelope once per distinct payload. A template
    with twenty lines would otherwise `json.loads()` the same (often
    60-200KB) document twenty times over the course of one import. The
    returned structure is shared between callers - treat it as read-only."""
    return json.loads(text)


#: Caps for `xberg_jsonpath_preview`, mirroring `import_preview`'s own
#: PREVIEW_MAX_ROWS/PREVIEW_MAX_CHARS constants (not imported from there -
#: see the "soft integration" note on `_preview_depends()` below for why
#: this module never hard-depends on that one).
_JSONPATH_PREVIEW_MAX_MATCHES = 25
_JSONPATH_PREVIEW_MAX_CHARS = 4000


class BaseImportPdfTemplateLine(models.Model):
    _inherit = "base.import.pdf.template.line"

    # Purely a view-visibility convenience (`invisible="extraction_mode !=
    # 'xberg'"` needs a real field on this model, not a cross-model dotted
    # path) - the same role `field_ttype`/`search_field_ttype` play
    # upstream. Not used for any decision in Python; code reads
    # `template_id.extraction_mode` directly.
    extraction_mode = fields.Selection(
        related="template_id.extraction_mode", string="Extraction mode"
    )
    xberg_jsonpath = fields.Char(
        string="Xberg JSONPath",
        help="Optional, only meaningful on an Xberg template. A JSONPath "
        "expression evaluated against the extracted document; `Pattern`'s "
        "regular expression is then matched against the result (one "
        "JSONPath match per line) instead of the whole document. Use it "
        "to narrow a big, noisy document down to just the value or column "
        "you actually want a regex to search, e.g. "
        "`$.tables[0].cellsByHeader[*].ITEM` for every row's item number. "
        "Left blank, `Pattern` matches the whole document as usual.",
    )
    xberg_jsonpath_preview = fields.Text(
        string="Xberg JSONPath Preview",
        compute="_compute_xberg_jsonpath_preview",
        store=False,
        help="What `Xberg JSONPath` currently selects from the template's "
        "sample document - i.e. the text `Pattern`'s regex will actually "
        "search once you write it. Requires a sample document on the "
        "template (the `import_preview` module's Sample Data tab).",
    )

    def _jsonpath_matches(self, jsonpath_expr, text):
        self.ensure_one()
        if _jsonpath_parse is None:
            raise UserError(
                self.env._("The `jsonpath-ng` library is not installed.")
            )
        return _compile_jsonpath(jsonpath_expr).find(_parse_document(text))

    @api.model
    def _jsonpath_to_text(self, value):
        """Render one JSONPath match value as a line of text - the same
        role `re.findall`/`match.group()` play for the regex engine, one
        match per line so `pattern`'s regex can use `re.MULTILINE` (as the
        base module's own "lines" extraction already does) to treat each
        match as its own row."""
        if isinstance(value, str):
            return value.strip()
        if value is None or isinstance(value, bool):
            return ""
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(value)  # list/dict: keep it inspectable rather than opaque

    def _xberg_narrow_text(self, text):
        """Narrow `text` (the whole extracted document) down to just what
        `xberg_jsonpath` selects, one JSONPath match per line - the input
        `pattern`'s regex actually searches, instead of the whole
        document. A no-op (returns `text` unchanged) unless this line's
        template uses the `xberg` extraction mode and `xberg_jsonpath` is
        actually set; `pattern` stays a plain regex either way, this only
        changes what it is matched against.
        """
        self.ensure_one()
        if self.extraction_mode != "xberg" or not self.xberg_jsonpath:
            return text
        matches = self._jsonpath_matches(self.xberg_jsonpath, text)
        return "\n".join(self._jsonpath_to_text(match.value) for match in matches)

    def _xberg_jsonpath_preview_depends(self):
        """`@api.depends` for `_compute_xberg_jsonpath_preview()`, built as
        a list rather than hardcoded: `template_id.sample_data` only
        exists as a field at all once `import_preview` is installed (it is
        that module's own addition to `base.import.pdf.template`), and an
        `@api.depends` path naming a field that does not exist anywhere in
        the registry fails at startup - so this path is included only when
        the field is actually there, checked once when computed fields are
        being wired up (`@api.depends(lambda self: ...)` calls this with
        `self` bound to the model, not a real record) - see
        `_preview_depends()` below for the same pattern already validated
        for `import_preview` integration.
        """
        depends = ["xberg_jsonpath"]
        if "sample_data" in self.env["base.import.pdf.template"]._fields:
            depends.append("template_id.sample_data")
        return depends

    @api.depends(lambda self: self._xberg_jsonpath_preview_depends())
    def _compute_xberg_jsonpath_preview(self):
        for line in self:
            try:
                line.xberg_jsonpath_preview = line._render_xberg_jsonpath_preview()
            except Exception as err:  # pylint: disable=W8138
                # Authoring a JSONPath is trial and error - an invalid
                # expression or a sample that isn't valid JSON is the
                # expected case mid-keystroke, not a bug; this compute
                # runs on every web_read and onchange, so it must never be
                # able to break the form.
                line.xberg_jsonpath_preview = self.env._(
                    "⚠ %(error_type)s: %(error)s",
                    error_type=type(err).__name__,
                    error=err,
                )

    def _render_xberg_jsonpath_preview(self):
        self.ensure_one()
        if self.extraction_mode != "xberg" or not self.xberg_jsonpath:
            return False
        template_fields = self.template_id._fields
        sample = self.template_id.sample_data if "sample_data" in template_fields else False
        if not sample:
            return self.env._(
                "Add a sample document on the template's Sample Data tab "
                "(the import_preview module) to preview this JSONPath."
            )
        matches = self._jsonpath_matches(self.xberg_jsonpath, sample)
        if not matches:
            return self.env._("No match.")
        rows = [self.env._("%s match(es):", len(matches))]
        for index, match in enumerate(matches[:_JSONPATH_PREVIEW_MAX_MATCHES], start=1):
            rows.append(f"{index:>3}. {self._jsonpath_to_text(match.value)!r}")
        if len(matches) > _JSONPATH_PREVIEW_MAX_MATCHES:
            rows.append(
                self.env._("… and %s more", len(matches) - _JSONPATH_PREVIEW_MAX_MATCHES)
            )
        return "\n".join(rows)[:_JSONPATH_PREVIEW_MAX_CHARS]

    def _get_column_values(self, text):
        return super()._get_column_values(self._xberg_narrow_text(text))

    def _get_field_value(self, text):
        return super()._get_field_value(self._xberg_narrow_text(text))

    def _preview_depends(self):
        """Soft integration with `import_preview`'s live-preview compute -
        not a hard dependency, this module never requires that one. The
        method is simply never called unless `import_preview` is also
        installed (only its `_compute_preview_result` invokes
        `_preview_depends()` at all), in which case `super()` correctly
        resolves to its implementation. `xberg_jsonpath` changes what a
        line extracts just as much as `pattern` does, so the preview needs
        to recompute when it changes too - without this, editing only
        `xberg_jsonpath` (never touching `pattern` itself) would not
        refresh the preview live.
        """
        return super()._preview_depends() + ["xberg_jsonpath"]
