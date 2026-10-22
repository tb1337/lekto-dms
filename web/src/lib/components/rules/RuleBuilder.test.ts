import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { newAction, newModel } from '#lib/rules/model.ts';
import RuleBuilder from './RuleBuilder.svelte';

const PERIOD = '0199a6c4-0000-7000-8000-0000000000f3';

const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	topics: [],
	fields: [
		{
			id: PERIOD,
			name: 'Bezugszeitraum',
			data_type: 'period',
			document_type_ids: null,
			required: false,
			required_document_type_ids: [],
			choices: []
		}
	],
	spaces: [],
	users: []
} as unknown as Lookup;

describe('RuleBuilder', () => {
	it('does not save while a period is written in a way it cannot read', async () => {
		const onsubmit = vi.fn();
		const model = newModel();
		model.name = 'Lohn';
		model.actions = [
			{
				key: newAction('set_field').key,
				type: 'set_field',
				field_id: PERIOD,
				value: { start: '', end: '' }
			}
		];
		render(RuleBuilder, {
			model,
			scope: 'user',
			lookup,
			spaces: [],
			errors: {},
			general: null,
			busy: false,
			cancelHref: '/rules',
			onsubmit
		});
		const save = screen.getByRole('button', { name: m.rule_save() }) as HTMLButtonElement;
		const notation = screen.getByLabelText(
			m.field_period_notation_of({ name: m.rule_condition_value() })
		);
		await fireEvent.input(notation, { target: { value: '2026-1' } });
		await fireEvent.blur(notation);
		expect(screen.getByText(m.field_period_unreadable())).toBeTruthy();
		expect(save.disabled).toBe(true);
		await fireEvent.submit(save.form as HTMLFormElement);
		expect(onsubmit).not.toHaveBeenCalled();

		await fireEvent.input(notation, { target: { value: '2026-11' } });
		await fireEvent.blur(notation);
		expect(save.disabled).toBe(false);
		await fireEvent.submit(save.form as HTMLFormElement);
		expect(onsubmit).toHaveBeenCalledOnce();
		expect(model.actions[0]).toMatchObject({ value: { start: '2026-11-01', end: '2026-11-30' } });
	});
});
