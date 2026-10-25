import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FieldDefinition, Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { newAction } from '#lib/rules/model.ts';
import ActionRow from './ActionRow.svelte';

const fields = [
	{ id: 'f1', name: 'Netto', key: 'netto', data_type: 'amount', document_type_ids: null }
] as unknown as FieldDefinition[];
const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	fields,
	spaces: [],
	users: []
} as unknown as Lookup;
const targets = [{ value: 'house', label: 'Haushalt' }];

afterEach(() => vi.unstubAllGlobals());

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

describe('a template of an action', () => {
	it('names the fields of the rule without asking for them again', async () => {
		const fetchMock = vi.fn<(request: Request) => Promise<Response>>(async () =>
			Response.json({ used: [], rendered: null, missing: null, error: null, values: null })
		);
		vi.stubGlobal('fetch', fetchMock);
		const action = newAction('set_title');
		render(ActionRow, { action, lookup, targets, onremove: vi.fn() });
		await new Promise((resolve) => setTimeout(resolve, 0));
		const asked = fetchMock.mock.calls.map(([request]) => new URL(request.url).pathname);
		expect(asked).not.toContain('/api/v1/fields');
	});
});
