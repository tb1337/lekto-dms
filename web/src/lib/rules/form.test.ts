import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/problem.ts';
import { m } from '#lib/paraglide/messages.js';
import { RuleForm } from './form.svelte.ts';
import { newModel } from './model.ts';

describe('the form of a rule', () => {
	it('shows the problems of the model, and holds its peace once it is in order', () => {
		const form = new RuleForm();
		const model = newModel();
		expect(form.check(model, [])).toBe(false);
		expect(form.errors.name).toBeTruthy();
		expect(form.general).toBe(m.rule_form_invalid());

		model.name = 'Strom';
		const condition = model.conditions.items[0];
		if (condition.kind === 'condition') condition.value = 'c1';
		model.actions = [{ key: 'a1', type: 'set_contact', contact_id: 'c1' }];
		expect(form.check(model, [])).toBe(true);
		expect(form.errors).toEqual({});
		expect(form.general).toBeNull();
	});

	it('hands back what was saved, or the problems the API named', async () => {
		const form = new RuleForm();
		const model = newModel();
		const save = vi.fn(async () => ({ id: 'r1' }));
		expect(await form.save(model, save)).toEqual({ id: 'r1' });
		expect(form.busy).toBe(false);

		const refused = vi.fn(async () => {
			throw new ApiError(
				422,
				{
					type: 'about:blank',
					title: 'Unprocessable',
					status: 422,
					detail: 'name: too long',
					existing_document_id: null,
					space_id: null,
					open_fields: null,
					blocking_spaces: null,
					second_factor_required: null,
					reason: null,
					errors: null
				},
				null
			);
		});
		expect(await form.save(model, refused)).toBeNull();
		expect(form.errors.name).toBe('too long');
		expect(form.general).toBe(m.rule_form_invalid());
		expect(form.busy).toBe(false);
	});
});
