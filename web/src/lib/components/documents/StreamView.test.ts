import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiQuery, NO_FILTERS } from '#lib/filters.ts';
import { m } from '#lib/paraglide/messages.js';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import StreamView from './StreamView.svelte';

const doc = (id: string, date: string) => ({
	id,
	title: `Abschlag ${id}`,
	document_date: date,
	created_at: `${date}T10:00:00Z`,
	contact_id: 'c1',
	document_type_id: 't1',
	lane: 'green'
});

describe('StreamView', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the lanes on the months with the target and the expected document', async () => {
		const api = fakeApi({
			'GET /api/v1/documents/stream': () => ({
				lanes: [
					{
						kind: 'series',
						documents: [doc('a', '2026-07-15'), doc('b', '2026-08-15')],
						contact_id: 'c1',
						document_type_id: 't1',
						number: 'V-1',
						target: doc('v', '2026-06-01'),
						expected: {
							next_date: '2026-09-15',
							next_period: null,
							state: 'overdue',
							cadence: 'monthly',
							spread_days: 2
						},
						parent: null,
						joins: null
					}
				],
				relations: [],
				truncated: true
			})
		});
		vi.stubGlobal('fetch', api);
		const query = { ...apiQuery({ ...NO_FILTERS, contacts: ['c1'] }) };
		render(StreamView, { props: { query, lookup: null } });
		const table = await screen.findByRole('table', { name: m.stream_lanes() });
		expect(within(table).getAllByRole('columnheader')).toHaveLength(5); // lanes + 4 months
		expect(within(table).getByRole('link', { name: /Abschlag v/ })).toBeTruthy();
		expect(within(table).getByText(/V-1/)).toBeTruthy();
		expect(screen.getByText(m.stream_truncated())).toBeTruthy();
		expect(calls(api)).toContain('GET /api/v1/documents/stream?contact_id=c1');
	});
});
