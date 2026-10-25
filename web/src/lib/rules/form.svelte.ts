/**
 * What the editor of a new rule and of a changed one share: the model is checked before it goes
 * to the API, its problems stand by their keys (`errors`) and as one line above the buttons
 * (`general`), and a save the API refused puts its problems there too.
 */
import { toast } from 'svelte-sonner';
import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { problemText } from '#lib/rules/describe.ts';
import { saveErrors } from '#lib/rules/errors.ts';
import { validate, type RuleModel } from '#lib/rules/model.ts';

export class RuleForm {
	/** The problems by key, as `validate` and `saveErrors` give them. */
	errors = $state<Record<string, string>>({});
	/** What belongs to no block. */
	general = $state<string | null>(null);
	/** While a save is on its way. */
	busy = $state(false);

	/** Whether `model` holds; else its problems are shown. */
	check(model: RuleModel, fields: readonly FieldDefinition[]): boolean {
		const problems = validate(model, fields);
		this.errors = Object.fromEntries(
			Object.entries(problems).map(([key, entry]) => [key, problemText(entry)])
		);
		this.general = Object.keys(this.errors).length > 0 ? m.rule_form_invalid() : null;
		return this.general === null;
	}

	/** Save through `save`: what it returns (with a toast), or null with the API's problems
	 * shown beside the blocks of `model`. */
	async save<T>(model: RuleModel, save: () => Promise<T>): Promise<T | null> {
		this.busy = true;
		try {
			const saved = await save();
			toast.success(m.rule_saved());
			return saved;
		} catch (error) {
			const { byKey, general } = saveErrors(error, model);
			this.errors = byKey;
			this.general = general ?? (Object.keys(byKey).length > 0 ? m.rule_form_invalid() : null);
			return null;
		} finally {
			this.busy = false;
		}
	}
}
