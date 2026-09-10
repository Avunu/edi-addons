// Copyright 2026 Avunu LLC (avu.nu)
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { TextField, textField } from "@web/views/fields/text/text_field";

import { useEffect } from "@odoo/owl";

/*
 * Vendored (microlighter 2.1.0, MIT - see static/lib/microlighter/). A tiny,
 * dependency-free syntax highlighter built on the CSS Custom Highlight API:
 * it registers matched ranges of the *existing* text node with
 * `CSS.highlights` instead of wrapping them in <span> markup, so read-only
 * JSON sample data can be colorized without ever touching what the field
 * actually holds.
 *
 * Its own README is explicit that it does not support live-editing a
 * <textarea> - only text held in a plain (or contentEditable) element. This
 * widget only overrides `TextField`'s *read-only* rendering (a bare `<span>`
 * upstream, `<pre><code class="language-json">` here) for exactly that
 * reason: the editable branch - the actual `<textarea>` a user types/pastes
 * into - is inherited from `TextField` completely unmodified and stays
 * plain text, matching microlighter's own guidance rather than fighting it.
 *
 * It is a genuine ES module (real `import`/`export`, plus a *dynamic*
 * `import()` inside it to lazy-load each TextMate grammar) - and Odoo's own
 * asset pipeline has no concept of that. `web.assets_backend` either
 * transpiles a `static/src` file's `import`/`export` into its own
 * `odoo.define()` wrapper (a regex-based converter, not a real parser - see
 * `odoo/tools/js_transpiler.py` - that has no chance of also handling a
 * *dynamic*, runtime-computed `import(...)` target) or, for anything else
 * (this library lives under `static/lib`, deliberately outside that
 * transpiler's reach), just concatenates the file as plain script text -
 * where a top-level `export` statement is a hard `SyntaxError` that broke
 * the entire bundle, not just this widget, the first time this was tried.
 *
 * The fix is to never hand the library to Odoo's bundler at all: a dynamic
 * `import()` *expression* (unlike a static `import` *statement*) is valid
 * in any script, transpiled or not, and the browser's own native module
 * loader takes over from there - fetching this file at its real, absolute
 * static URL and correctly resolving every import inside it (including the
 * dynamic per-grammar one), completely bypassing Odoo's bundler. Browsers
 * cache a module by URL, so calling this on every highlight is cheap after
 * the first time.
 */
const loadHighlightAll = () =>
    import("/import_preview/static/lib/microlighter/index.js").then(
        (module) => module.highlightAll
    );

export class JsonHighlightField extends TextField {
    static template = "import_preview.JsonHighlightField";

    setup() {
        super.setup();
        // `highlightAll()` re-scans every `pre > code[class*="language-"]`
        // block currently in the document (cheap - there are at most one or
        // two visible at once: the template form and/or one open line
        // dialog) and is safe to call repeatedly - it clears its own
        // previously registered ranges first. Only worth doing in the
        // read-only branch; the editable textarea has nothing for it to
        // find (see the module docstring above).
        useEffect(
            () => {
                if (this.props.readonly) {
                    loadHighlightAll().then((highlightAll) => highlightAll());
                }
            },
            () => [this.props.readonly, this.props.record.data[this.props.name]]
        );
    }
}

export const jsonHighlightField = {
    ...textField,
    component: JsonHighlightField,
    displayName: _t("Text (JSON syntax highlighting)"),
};

registry.category("fields").add("json_highlight", jsonHighlightField);
