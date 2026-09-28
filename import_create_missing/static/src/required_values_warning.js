// Copyright 2026 Avunu LLC (avu.nu)
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";
import { X2ManyFieldDialog } from "@web/views/fields/relational_utils";

const LINE_MODEL = "base.import.pdf.template.line";

/**
 * The line's own server-side summary of what its New Document Values table
 * still leaves unset (`create_missing_warning`), or null when there is
 * nothing to say.
 *
 * Deliberately just *reading a field* rather than re-deriving anything in
 * JS: "which fields does this model require, and which of those has an
 * Odoo default" is knowledge only the server has, and duplicating even a
 * simplified version of it here would drift from
 * `create_field_spec.required_field_specs()` the first time a model
 * changes.
 *
 * @param {import("@web/model/relational_model/record").Record} record
 * @returns {string | null}
 */
export function missingRequiredWarning(record) {
    if (!record || record.resModel !== LINE_MODEL) {
        return null;
    }
    if (!record.data.create_missing) {
        return null;
    }
    return record.data.create_missing_warning || null;
}

/**
 * Show the warning, if there is one. Never blocks anything: by the time
 * this runs the save has already happened.
 *
 * @param {Object} env
 * @param {import("@web/model/relational_model/record").Record} record
 */
function notifyMissingRequired(env, record) {
    const message = missingRequiredWarning(record);
    if (!message) {
        return;
    }
    env.services.notification.add(message, {
        type: "warning",
        title: _t("Missing required values"),
    });
}

/*
 * The line is edited in an x2many dialog (the template form's Lines tab),
 * so its save goes through `X2ManyFieldDialog.save()` - not through any
 * form controller hook. Patched rather than subclassed because the dialog
 * component is instantiated by `X2ManyField` itself, with no seam to hand
 * it a different class.
 *
 * `super.save()` is awaited and its result respected, so an actually
 * invalid record (a genuinely required *template* field left empty) still
 * fails exactly as before - this only ever adds a notification on a save
 * that already succeeded. `this.record` is captured up front because
 * Save & New swaps it for a fresh record before returning.
 */
patch(X2ManyFieldDialog.prototype, {
    async save(params) {
        const record = this.record;
        const saved = await super.save(params);
        if (saved) {
            notifyMissingRequired(this.env, record);
        }
        return saved;
    },
});

/*
 * The same warning for the full-form path - reached from the dialog's
 * expand button, or any action that opens a line directly.
 * `onRecordSaved` only runs after a save that really happened (not on an
 * invalid record, and not when there was nothing to save), which is
 * exactly when the warning is worth showing.
 */
export class ImportCreateMissingLineFormController extends FormController {
    async onRecordSaved(record, changes) {
        const result = await super.onRecordSaved(record, changes);
        notifyMissingRequired(this.env, record);
        return result;
    }
}

registry.category("views").add("import_create_missing_line_form", {
    ...formView,
    Controller: ImportCreateMissingLineFormController,
});
