# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import re
from itertools import zip_longest

from odoo import models


class BaseImportPdfTemplate(models.Model):
    _inherit = "base.import.pdf.template"

    def _get_table_info_data(self, text):
        """Same contract as the base method (a list of rows, each a list of
        cell strings, one column per "lines" child line in sequence), but
        each column now comes from `line._get_column_values(text)` instead
        of a regex hardcoded here. That per-line method is the extension
        point other pattern engines (see `import_via_xberg`'s JSONPath
        columns) and tooling (see `import_preview`'s live match preview)
        plug into, instead of overriding this whole method and duplicating
        the row-assembly logic below.
        """
        child_lines = self.line_ids.filtered(
            lambda x: x.related_model == "lines"
            and x.value_type != "fixed"
            and x.pattern
        )
        columns = [line._get_column_values(text) for line in child_lines]
        if not columns:
            # The base implementation indexes `data_keys[0]` unconditionally
            # here, which raises IndexError when no child line has a pattern
            # yet (e.g. a template still being built). An empty table is the
            # correct answer instead.
            return []
        # `_get_field_values_from_table_item()` maps a row onto `child_lines`
        # *by position*, so a column shorter than the others must be padded
        # rather than dropped: the base implementation simply appends
        # nothing for a missing cell, which shifts every later column of
        # that row by one. Padding with "" is safe because that method
        # already skips falsy cells (`if item_lenght >= sequence and
        # item[sequence]`).
        return [list(row) for row in zip_longest(*columns, fillvalue="")]


class BaseImportPdfTemplateLine(models.Model):
    _inherit = "base.import.pdf.template.line"

    def _get_column_values(self, text):
        """The values this line contributes to a "lines" table, as a column.

        This is the regex implementation lifted unchanged from the base
        module's `_get_table_info_data()`; a module adding a different
        pattern language (e.g. JSONPath) overrides this instead of the
        table-assembly method above.
        """
        self.ensure_one()
        if not self.pattern:
            return []
        values = []
        for match in re.finditer(self.pattern, text, re.MULTILINE):
            groups = match.groups(0)
            # The base module does `match.groups(0)[0]` unconditionally,
            # which raises IndexError for a pattern with no capturing group
            # (e.g. a plain literal used as a column separator probe). Fall
            # back to the whole match in that case.
            match_group = groups[0] if groups else match.group(0)
            values.append(str(match_group).strip())
        return values

    def _without_pattern(self):
        """Return an in-memory copy of `self` whose `pattern` is empty.

        A pattern engine whose selection step already consumes the pattern
        before `_process_value()` runs (e.g. JSONPath: the match was found
        while extracting `value` in the first place, so `value` should not
        be run back through the pattern) still needs the base module's
        `_process_value()` post-processing tail: date/float conversion,
        `mapped_ids`, `search_field_id`, `default_value`. Call
        `super()._process_value(value)` on the record this returns instead
        of duplicating that ~25-line tail, so it cannot drift from upstream.
        """
        self.ensure_one()
        if self.id:
            # Real record: `new(origin=self)` makes every stored,
            # non-computed field (date_format, mapped_ids, search_field_id,
            # default_value, ...) fall through to `self` for reads - see the
            # "new record with origin" branch of `odoo.fields.Field.__get__`.
            return self.new({"pattern": False}, origin=self)
        # `self` is ALREADY an in-memory/NewId record - this is the normal
        # case for a live preview compute (onchange) or `odoo.tests.Form`,
        # which is what the base module's own `_process_form()` uses to
        # build records. Calling `new(origin=self)` here would build a NewId
        # whose origin is *another* NewId, and `odoo.models.origin_ids()`
        # drops those (`NewId.__bool__` is False), so the twin's `_origin`
        # would come back empty and every stored field would silently fall
        # back to its field *default* instead of `self`'s actual in-memory
        # value. Copy the values across explicitly instead.
        values = {
            name: self[name]
            for name, field in self._fields.items()
            if field.store and not field.compute and name not in ("id", "pattern")
        }
        return self.new(values)
