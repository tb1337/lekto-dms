import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Lens } from '#lib/lenses.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { choose } from '#lib/testing/select.ts';
import LensEditor, { type LensDraft } from './LensEditor.svelte';

const TODAY = new Date(2026, 9, 20);

const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [{ id: 't1', name: 'zu bezahlen', path: ['zu bezahlen'], scope: 'document' }],
	fields: [
		{ id: 'due', name: 'Fällig am', data_type: 'date' },
		{ id: 'total', name: 'Betrag', data_type: 'amount' },
		{ id: 'note', name: 'Notiz', data_type: 'text' }
	],
	spaces: [],
	users: []
} as unknown as Lookup;

const draft: LensDraft = {
	filter: { tag_ids: ['t1'], document_period: 'last_12_months' },
	query: null,
	sort: null,
	sortField: null,
	layout: 'list'
};

const LENS: Lens = {
	id: 'l1',
	name: 'Zu bezahlen',
	position: 0,
	filter: {
		contact_ids: [],
		document_type_ids: [],
		contact_group_ids: [],
		document_type_group_ids: [],
		topic_ids: [],
		tag_ids: ['t1'],
		space_ids: [],
		field_id: null,
		document_date_from: null,
		document_date_to: null,
		document_period: null,
		facts: []
	},
	query: null,
	sort: null,
	sort_field_id: null,
	grouping: 'none',
	layout: 'grid',
	card_field_ids: ['total'],
	due_field_id: null,
	created_at: '2026-10-20T10:00:00Z',
	updated_at: '2026-10-20T10:00:00Z'
};

const requests: { method: string; path: string; body: unknown }[] = [];

function api() {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (request: Request) => {
			const body = request.method === 'GET' ? null : await request.text();
			const parsed = body ? JSON.parse(body) : null;
			requests.push({ method: request.method, path: new URL(request.url).pathname, body: parsed });
			if (request.method === 'DELETE') return new Response(null, { status: 204 });
			return new Response(JSON.stringify({ ...LENS, ...parsed }), {
				status: request.method === 'POST' ? 201 : 200,
				headers: { 'content-type': 'application/json' }
			});
		})
	);
}

function editor(initial: Lens | null = null) {
	const onsaved = vi.fn();
	const ondeleted = vi.fn();
	render(LensEditor, {
		open: true,
		initial,
		draft,
		lookup,
		today: TODAY,
		onsaved,
		ondeleted
	});
	return { onsaved, ondeleted };
}

afterEach(() => {
	requests.length = 0;
	vi.unstubAllGlobals();
});

describe('the lens editor', () => {
	it('makes a new lens from the filters of the page, a moving period as such', async () => {
		api();
		const user = userEvent.setup();
		const { onsaved } = editor();
		const dialog = screen.getByRole('dialog');
		expect(within(dialog).getByText(/12/)).toBeTruthy();
		expect(within(dialog).getByText('zu bezahlen')).toBeTruthy();
		await user.type(within(dialog).getByLabelText(m.lens_name()), 'Zu bezahlen');
		// Grouping by deadline needs a deadline.
		const byDue = within(dialog).getByRole('button', { name: m.lens_grouping_due() });
		expect((byDue as HTMLButtonElement).disabled).toBe(true);
		expect(within(dialog).getByText(m.lens_grouping_due_hint())).toBeTruthy();
		await choose(user, within(dialog).getByLabelText(m.lens_due()), 'due');
		expect(within(dialog).queryByText(m.lens_grouping_due_hint())).toBeNull();
		await user.click(byDue);
		await user.click(within(dialog).getByRole('button', { name: m.save() }));
		await waitFor(() => expect(onsaved).toHaveBeenCalled());
		expect(requests[0]).toMatchObject({
			method: 'POST',
			path: '/api/v1/lenses',
			body: {
				name: 'Zu bezahlen',
				filter: draft.filter,
				grouping: 'due',
				due_field_id: 'due',
				layout: 'list',
				sort: null
			}
		});
		expect(onsaved.mock.calls[0][1]).toBe(true);
	});

	it('changes a lens: a sort by a field, card fields added and moved', async () => {
		api();
		const user = userEvent.setup();
		const { onsaved } = editor(LENS);
		const dialog = screen.getByRole('dialog');
		await choose(user, within(dialog).getByLabelText(m.lens_sort()), 'field:due');
		await choose(user, within(dialog).getByLabelText(m.lens_field_add()), 'due');
		await user.click(
			within(dialog).getByRole('button', { name: m.lens_field_up({ name: 'Fällig am' }) })
		);
		await user.click(within(dialog).getByRole('button', { name: m.save() }));
		await waitFor(() => expect(onsaved).toHaveBeenCalled());
		expect(requests[0]).toMatchObject({
			method: 'PATCH',
			path: '/api/v1/lenses/l1',
			body: { sort: 'field', sort_field_id: 'due', card_field_ids: ['due', 'total'] }
		});
		expect(requests[0].body).not.toHaveProperty('filter');
	});

	it('deletes a lens after asking', async () => {
		api();
		const user = userEvent.setup();
		const { ondeleted } = editor(LENS);
		await user.click(screen.getByRole('button', { name: m.lens_delete({ name: 'Zu bezahlen' }) }));
		await user.click(await screen.findByRole('button', { name: m.delete_title() }));
		await waitFor(() => expect(ondeleted).toHaveBeenCalledWith('l1'));
		expect(requests.at(-1)).toMatchObject({ method: 'DELETE', path: '/api/v1/lenses/l1' });
	});
});
