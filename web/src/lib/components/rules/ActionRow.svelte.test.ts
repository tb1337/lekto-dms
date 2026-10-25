import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FieldDefinition, Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { newAction, type SetFieldNode } from '#lib/rules/model.ts';
import ActionRow from './ActionRow.svelte';

const fields = [
	{ id: 'n', name: 'Stunden', key: 'stunden', data_type: 'number', document_type_ids: null }
] as unknown as FieldDefinition[];
const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	fields,
	spaces: [],
	users: []
} as unknown as Lookup;

afterEach(() => vi.unstubAllGlobals());

describe('the switch between a fixed value and a template', () => {
	it('stays where it is while the person types', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () =>
				Response.json({ used: [], rendered: null, missing: null, error: null, values: null })
			)
		);
		const user = userEvent.setup();
		// The page holds its model in state, as here.
		const action = $state({
			...newAction('set_field'),
			field_id: 'n',
			value: '12.5'
		}) as SetFieldNode;
		render(ActionRow, { action, lookup, targets: [], onremove: vi.fn() });
		const fixed = screen.getByRole('button', { name: m.rule_value_fixed() });
		expect(fixed.getAttribute('aria-pressed')).toBe('true');

		// Emptied or half typed, a number is no template: the input stays.
		const input = screen.getByLabelText(m.rule_condition_value());
		await user.clear(input);
		await user.type(input, '-');
		expect(
			screen.getByRole('button', { name: m.rule_value_fixed() }).getAttribute('aria-pressed')
		).toBe('true');
		expect(action.templated).toBe(false);
	});

	it('starts a new action with a fixed value', () => {
		const action = $state({ ...newAction('set_field'), field_id: 'n' }) as SetFieldNode;
		render(ActionRow, { action, lookup, targets: [], onremove: vi.fn() });
		const fixed = screen.getByRole('button', { name: m.rule_value_fixed() });
		expect(fixed.getAttribute('aria-pressed')).toBe('true');
	});
});
