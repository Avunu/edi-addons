# Import Preview

A persistent reference sample per `base_import_pdf_by_template` template, and a live preview of what each line's pattern actually matches while you edit it - directly in the line dialog, without uploading a file or leaving the form.

## Why

The base module's own preview wizard (the "Preview" stat button) needs a file re-uploaded on every use and shows nothing while a pattern is actually being typed in a line's dialog form. There is no persistent reference document, so authoring a template means alternating between the line dialog and a separate wizard, guessing at what each regex actually captures.

## What it adds

-   `sample_data` (Text) on `base.import.pdf.template`, on a new "Sample Data" notebook page - a persistent reference document for the template: plain text for most extraction modes, or a JSON envelope for a mode like `import_via_xberg`'s `xberg`.
-   `sample_file` on the same page - upload a file and its `onchange` runs the template's own extraction pipeline (reusing `wizard.base.import.pdf.preview._parse_pdf()`) to fill `sample_data` automatically, rather than requiring it to be hand-typed.
-   `preview_summary` on the template - the assembled header values and table rows for the current sample, using the same `_get_table_info()` / `_get_field_child_values()` a real import uses. This is where cross-column misalignment between lines becomes visible.
-   `preview_result` on `base.import.pdf.template.line`, shown directly under `pattern` in the line dialog - what *this* line's pattern currently matches against the template's sample, refreshed as you type. It is deliberately engine-agnostic: it calls the same `_get_field_value()` / `_get_column_values()` / `_process_value()` methods a real import calls, so it works for regex out of the box and for any other pattern engine (e.g. `import_via_xberg`'s JSONPath) the moment that module is also installed, with no dependency between the two.
-   JSON syntax highlighting on every read-only rendering of `sample_data` (the line dialog's mirror, and a second, read-only copy shown right under the editable one on the template's own Sample Data tab) - see "Syntax highlighting" below.

## Syntax highlighting

`sample_data` often holds a JSON document (an `import_via_xberg` template's sample is the whole extracted-document envelope, easily 60-200KB) - a wall of unbroken text otherwise. A new field widget, `json_highlight` (`static/src/json_highlight_field/`), colorizes it using [microlighter](https://github.com/davatron5000/microlighter) (vendored, MIT, `static/lib/microlighter/` - see the file header comments there for exactly which parts are used).

microlighter is built on the browser's CSS Custom Highlight API: it registers matched text ranges directly against the *existing* text node instead of wrapping them in `<span>` markup, and its own docs are explicit that this only works against read-only text (or a `contentEditable` element) - not a live `<textarea>`. So `json_highlight` only overrides `TextField`'s read-only rendering (`<pre><code class="language-json">` instead of a bare `<span>`); the actual editable `sample_data` textarea on the template's Sample Data tab - where you paste or type a sample - is left completely alone, unhighlighted, exactly as `TextField` always renders it. The read-only, highlighted copy sits directly below it instead, updating as you type. The Custom Highlight API has shipped in every major engine (including Firefox) since mid-2025, so this is not a compatibility gamble at this point.

## How the live update works

The line dialog is a separate form (`form_view_ref`) opened over the o2m field, not an inline list - so the preview has to recompute from the *parent* template's in-memory, possibly-unsaved `sample_data`. This works because:

1.  `preview_result`'s `@api.depends` (via `PREVIEW_DEPENDS` / `_preview_depends()`) lists every field that affects it, including `template_id.sample_data`.
2.  A field only gets `on_change="1"` on its view node when some *other* field in the same view depends on it - since the line dialog contains both `pattern` and `preview_result`, editing `pattern` fires an onchange.
3.  The web client sends an x2many child's onchange RPC with the parent's own unsaved changes attached, which the ORM turns into an in-memory parent record - so `self.template_id.sample_data` inside the compute already reflects what you just typed on the template, even if the template has never been saved.

One gap to know about: opening an *existing* line for the first time reads `preview_result` off the saved record, so if you paste sample data and open a line dialog without saving the template first, that first render can be stale. It self-corrects on the next keystroke in the dialog (any `on_change="1"` field). Uploading via `sample_file` largely avoids the scenario, since it commits `sample_data` through a normal onchange rather than requiring you to leave the field dirty.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i import_preview \
  --test-enable --test-tags /import_preview --stop-after-init
```

`test_preview_updates_from_unsaved_parent_sample_data` is the load-bearing test: it drives the actual line dialog through `odoo.tests.Form` (the same onchange machinery the web client uses) with an unsaved parent template, and asserts the preview reflects the parent's in-memory `sample_data`.
