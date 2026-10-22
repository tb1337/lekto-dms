import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { newAction } from '#lib/rules/model.ts';
import ActionRow from './ActionRow.svelte';

const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	fields: [],
	spaces: [],
	users: []
} as unknown as Lookup;
const targets = [{ value: 'house', label: 'Haushalt' }];

function fileInto(space: string) {
	const action = newAction('set_space');
	if (action.type === 'set_space') action.space_id = space;
	render(ActionRow, { action, lookup, targets, onremove: vi.fn() });
}

describe('filing into a space', () => {
	it('keeps a space the caller may not file into and says why saving needs another', () => {
		fileInto('closed');
		expect(screen.getByText(m.rule_space_unreachable_hint())).toBeTruthy();
	});

	it('says nothing about a space the caller files into', () => {
		fileInto('house');
		expect(screen.queryByText(m.rule_space_unreachable_hint())).toBeNull();
	});
});
