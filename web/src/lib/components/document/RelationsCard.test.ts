import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import RelationsCard from './RelationsCard.svelte';

type Relations = components['schemas']['RelationsOut'];

const other = (id: string, title: string) => ({
	id,
	title,
	document_type_id: null,
	contact_id: null,
	document_date: '2026-06-04'
});

const suggested: Relations = {
	refers_to: [],
	referred_by: [],
	suggested: [
		{
			document: other('invoice', 'Rechnung 4711'),
			origin: 'lekto',
			state: 'suggested',
			evidence: { kind: 'fact', fact_kind: 'invoice_number', value: '4711' },
			created_at: '2026-07-20T10:00:00Z',
			decided_at: null,
			changeable: true
		}
	],
	editable: true
};

const accepted: Relations = {
	...suggested,
	suggested: [],
	refers_to: [{ ...suggested.suggested[0], state: 'set', decided_at: '2026-07-21T10:00:00Z' }]
};

describe('RelationsCard', () => {
	const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
	const json = (body: unknown) =>
		new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });

	beforeEach(() => {
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (request) =>
			json(request.method === 'POST' ? accepted : suggested)
		);
		vi.stubGlobal('fetch', fetchMock);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows a suggestion with its evidence and accepts it', async () => {
		const user = userEvent.setup();
		render(RelationsCard, { props: { documentId: 'reminder', lookup: null } });
		expect(await screen.findByText('Rechnung 4711')).toBeTruthy();
		expect(screen.getByText(m.relations_suggested())).toBeTruthy();
		expect(screen.getByText(/4711$/, { selector: 'span' })).toBeTruthy();
		await user.click(
			screen.getByRole('button', { name: m.relations_accept({ title: 'Rechnung 4711' }) })
		);
		await waitFor(() => expect(screen.getByText(m.relations_refers_to())).toBeTruthy());
		const posted = fetchMock.mock.calls.find(([request]) => request.method === 'POST')?.[0];
		expect(new URL(posted!.url).pathname).toBe('/api/v1/documents/reminder/relations');
		expect(await posted!.clone().json()).toEqual({ document_id: 'invoice' });
		expect(screen.queryByText(m.relations_suggested())).toBeNull();
	});

	it('offers nothing to change to a reader', async () => {
		const read = { ...accepted.refers_to[0], changeable: false };
		fetchMock.mockImplementation(async () =>
			json({ ...accepted, refers_to: [read], editable: false })
		);
		render(RelationsCard, { props: { documentId: 'reminder', lookup: null } });
		expect(await screen.findByText('Rechnung 4711')).toBeTruthy();
		expect(screen.queryByRole('button')).toBeNull();
	});
});
