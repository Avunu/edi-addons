# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import asyncio
import base64
import enum
import json
import logging

from odoo import models

logger = logging.getLogger(__name__)

try:
    import xberg
except ImportError:  # pragma: no cover - external_dependencies covers this
    xberg = None

#: Cap on `_to_jsonable()`'s recursion depth. `_seen` (id-based) already
#: rules out cycles; this guards against a legitimately deep but enormous
#: tree (e.g. a PDF with hundreds of pages, or `children` from a nested
#: archive) turning into an unbounded conversion.
_TO_JSONABLE_MAX_DEPTH = 12


def _to_jsonable(obj, _seen=None, _depth=0):
    """Convert an `xberg` result object into plain JSON-safe Python data.

    `xberg`'s result classes (`ExtractedDocument`, `Table`, `Metadata`, ...)
    are native compiled objects: unlike the CLI's `--format json`, the
    Python bindings expose no `to_json()`/`to_dict()` on most of them (only
    an asymmetric `from_json()` classmethod to build one FROM json).

    Some of them - empirically, the ones wrapping a Rust tagged union/enum
    with data, e.g. `FormatMetadata` - DO implement `__repr__` as their own
    compact, correct JSON serialisation (their Rust `Debug` impl bridged
    straight into Python), and that is the ONLY faithful way to read them:
    walking such an object's `dir()` instead reflects over its raw variant
    accessors (something like `link_type.is_email`, `.is_anchor`, ...) and
    reconstructs a bogus, deeply self-referential "all variants, mostly
    null" tree rather than the single active one - a multi-megabyte,
    99%-null blowup from what should be a few hundred bytes. So a JSON
    `repr()` is always preferred when one is available; only objects with
    the default `<builtins.X object at 0x...>` repr (`ExtractedDocument`,
    `Metadata`, `Table`, `DocumentCounts`, ... - anything that is a plain
    struct, not a tagged union) fall through to the `dir()`-based walk.

    Binary payloads (e.g. an extracted image's raw bytes, only present when
    the caller's config explicitly asks for image extraction) are dropped
    rather than embedded - a JSONPath pattern operates on text and table
    structure, never on pixel data, and inlining base64 blobs here would
    make the JSON envelope reused by `_get_field_value()` prohibitively
    large to `json.loads()` (and re-cache) on every pattern evaluation.
    """
    if _seen is None:
        _seen = set()
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, bytes):
        return None
    if isinstance(obj, enum.Enum):
        return obj.name
    if _depth >= _TO_JSONABLE_MAX_DEPTH:
        return None
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v, _seen, _depth + 1) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v, _seen, _depth + 1) for k, v in obj.items()}
    try:
        return json.loads(repr(obj))
    except (TypeError, ValueError):
        pass
    oid = id(obj)
    if oid in _seen:
        return None
    # Mutate the one `_seen` set shared by the whole conversion (never
    # rebind to a copy) - a repeated reference must be cut off wherever it
    # is next encountered, whether that is a true cycle (an object nested
    # inside itself) or just the same object reachable from two sibling
    # attributes. Rebinding to `_seen | {oid}` here previously gave each
    # branch its own private copy, so two siblings each independently
    # "discovered" the same object as if for the first time.
    _seen.add(oid)
    names = [
        name
        for name in dir(obj)
        if not name.startswith("_") and not callable(getattr(obj, name, None))
    ]
    if not names:
        return str(obj)
    return {name: _to_jsonable(getattr(obj, name), _seen, _depth + 1) for name in names}


def _transpose_table_cells(cells):
    """Derive two row-keyed views of a table's raw `[[row], [row], ...]`
    cell grid, treating row 0 as column headers:

    - `cells_by_header`: one dict per DATA row (row 0 itself is never
      included), keyed by that column's header text. A column whose
      header cell is blank (e.g. an image-only column - see
      `tests/data/` fixtures) is omitted, since there is nothing stable
      to key it by; if two columns share a header, the later one wins -
      neither is renamed or dropped, so `cells_by_index` below is the
      fallback for either case.
    - `cells_by_index`: the same rows, keyed by stringified column index
      ("0", "1", ...) instead of header text - always present regardless
      of whether a header exists, and immune to duplicate headers.

    The base grid does not let a JSONPath pattern express "this column,
    across every row" without hardcoding its position (`cells[1:].[2]`),
    which breaks the moment column order shifts between documents from
    the same sender. `$.tables[0].cellsByHeader[*].Item` does not have
    that problem - but only for a table that actually *has* a header
    row. Plenty of tables in a real document do not (a label/value pair
    table like `[["Order #:", "Y2..."], ["Dealer:", "H510..."]]` has no
    header row at all - row 0 is just its first data pair), and blindly
    applying this to one would turn it into nonsense: the first row's
    *values* would become header keys for the second row. Callers add
    these as extra keys alongside the untouched `cells`, never replacing
    it, so which view fits a given table is left to whoever writes the
    pattern - not guessed here.
    """
    if not cells:
        return [], []
    header_row, data_rows = cells[0], cells[1:]
    cells_by_header = []
    cells_by_index = []
    for row in data_rows:
        cells_by_index.append({str(i): value for i, value in enumerate(row)})
        row_by_header = {}
        for i, value in enumerate(row):
            if i >= len(header_row):
                break
            header = header_row[i]
            if isinstance(header, str):
                header = header.strip()
            if header:
                row_by_header[header] = value
        cells_by_header.append(row_by_header)
    return cells_by_header, cells_by_index


def _add_table_cell_views(document_json):
    """Add `cellsByHeader`/`cellsByIndex` to every table in a converted
    document's `tables` list, in place - see `_transpose_table_cells()`.
    """
    for table in document_json.get("tables") or []:
        by_header, by_index = _transpose_table_cells(table.get("cells") or [])
        table["cellsByHeader"] = by_header
        table["cellsByIndex"] = by_index
    return document_json


class WizardBaseImportPdfMixin(models.AbstractModel):
    _inherit = "wizard.base.import.pdf.mixin"

    def _read_bytes_file(self, fileobj):
        """Read back the temp file `simple_pdf_text_extraction()` wrote to
        disk, as raw bytes (that method hands `_pdf_text_extraction_xberg()`
        only the file object, not the original bytes).

        Mirrors `import_from_email`'s `_read_text_file()`: that method
        writes to `fileobj` but never flushes it before calling us, so a
        small document can read back as 0 bytes without an explicit flush.
        """
        fileobj.flush()
        with open(fileobj.name, "rb") as f:
            return f.read()

    def _xberg_config(self):
        """The `FileExtractionConfig` (as a dict - `xberg.ExtractInput`
        accepts one directly, no need to build the typed config objects)
        for this extraction: the template's own `xberg_config` JSON,
        defaulted with a timeout from `ir.config_parameter` when the
        template doesn't set one itself.
        """
        template = self.template_id if "template_id" in self._fields else False
        raw = template.xberg_config if template else False
        config = json.loads(raw) if raw else {}
        config.setdefault(
            "timeout_secs",
            int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("import_via_xberg.timeout", 300)
            ),
        )
        return config

    def _pdf_text_extraction_xberg(self, fileobj):
        res = False
        try:
            data = self._read_bytes_file(fileobj)
            extract_input = xberg.ExtractInput(
                kind=xberg.ExtractInputKind.BYTES,
                bytes=data,
                config=self._xberg_config(),
            )
            # `xberg.extract()` is async-only (no sync wrapper in the
            # library); Odoo's request/ORM stack is entirely synchronous,
            # so bridge with a fresh event loop per call. `asyncio.run()`
            # is safe to call from any thread - each call gets its own
            # loop, and Odoo's threaded workers never run one of their own.
            result = asyncio.run(xberg.extract(extract_input))
            if result.errors:
                raise xberg.XbergError(
                    "; ".join(e.message for e in result.errors)
                )
            document = result.results[0]
            document_json = _add_table_cell_views(_to_jsonable(document))
            res = [json.dumps(document_json)]
            logger.info("Text extraction made with xberg")
        except Exception as e:  # pylint: disable=W8138
            logger.warning("Text extraction with xberg failed. Error: %s", e)
        return res

    def _skip_xberg_grouped_parsing(self):
        """True when we can positively determine that no template this
        wizard could match actually uses the `xberg` extraction mode.
        Defaults to False (never skip) when that cannot be determined - e.g.
        this wizard has no `parent_id` (only
        `wizard.base.import.pdf.upload.line` does)."""
        if "parent_id" not in self._fields:
            return False
        allowed_templates = self.parent_id.allowed_template_ids
        if not allowed_templates:
            return False
        return "xberg" not in allowed_templates.mapped("extraction_mode")

    def _parse_pdf_grouped(self):
        """Same contract as the base method - try every registered
        extraction mode against the attachment, for template auto-detection
        before any one template (and therefore extraction mode) is known -
        except `xberg` is skipped (reported as `False`, same as any mode
        that fails to extract) when `_skip_xberg_grouped_parsing()` says
        nothing could need it. A real extraction (parsing the document,
        possibly OCR) is not free; there is no reason to pay that cost on
        every upload when no template on the instance uses this mode.
        """
        res = {}
        extraction_modes = dict(
            self._fields["extraction_mode"]._description_selection(self.env)
        )
        skip_xberg = "xberg" in extraction_modes and self._skip_xberg_grouped_parsing()
        file_data = base64.b64decode(self.attachment_id.datas)
        for extraction_mode in extraction_modes:
            if extraction_mode == "xberg" and skip_xberg:
                res[extraction_mode] = False
                continue
            self.extraction_mode = extraction_mode
            res[extraction_mode] = self._fallback_parse_pdf(file_data)
        return res
