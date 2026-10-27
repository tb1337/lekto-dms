import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiQuery, NO_FILTERS } from '#lib/filters.ts';
import { formatNumber } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import StreamView from './StreamView.svelte';

const doc = (id: string, date: string, lane: string | null = 'green') => ({
	id,
	title: `Abschlag ${id}`,
	document_date: date,
	created_at: `${date}T10:00:00Z`,
	contact_id: 'c1',
	document_type_id: 't1',
	lane
});

const series = (documents: object[], changes: object = {}) => ({
	kind: 'series',
	documents,
	contact_id: 'c1',
	document_type_id: 't1',
	number: 'V-1',
	target: null,
	expected: null,
	parent: null,
	joins: null,
	folded: false,
	...changes
});

describe('StreamView', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the lanes on the months with the target and the expected document', async () => {
		const api = fakeApi({
			'GET /api/v1/documents/stream': () => ({
				lanes: [
					series([doc('a', '2026-07-15'), doc('b', '2026-08-15')], {
						target: doc('v', '2026-06-01'),
						expected: {
							next_date: '2026-09-15',
							next_period: null,
							state: 'overdue',
							cadence: 'monthly',
							spread_days: 2
						}
					})
				],
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

	it('folds a stretch without documents and marks a document in processing', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/documents/stream': () => ({
					lanes: [
						series([doc('a', '2026-07-15'), doc('p', '2026-08-15', null)], {
							target: doc('v', '2021-06-01')
						})
					],
					truncated: false
				})
			})
		);
		render(StreamView, { props: { query: apiQuery(NO_FILTERS), lookup: null } });
		const table = await screen.findByRole('table', { name: m.stream_lanes() });
		const gap = m.stream_gap({ count: formatNumber(60) }); // 2021-07 to 2026-06
		expect(within(table).getByRole('columnheader', { name: gap })).toBeTruthy();
		expect(within(table).getAllByRole('columnheader')).toHaveLength(5); // lanes, 06/21, gap, 07, 08
		expect(within(table).getByRole('link', { name: /Abschlag v/ })).toBeTruthy();
		expect(within(table).getByText(new RegExp(m.inbox_processing()))).toBeTruthy();
	});

	it('shows the lanes beyond the limit on demand', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/documents/stream': () => ({
					lanes: [
						series([doc('a', '2026-07-15'), doc('b', '2026-08-15')]),
						series([doc('c', '2026-07-16'), doc('d', '2026-08-16')], { folded: true }),
						{
							...series([doc('e', '2026-08-20')]),
							kind: 'branch',
							parent: 1,
							joins: 'd',
							folded: true
						},
						{ ...series([doc('s', '2026-05-01')]), kind: 'single', number: null }
					],
					truncated: false
				})
			})
		);
		render(StreamView, { props: { query: apiQuery(NO_FILTERS), lookup: null } });
		const table = await screen.findByRole('table', { name: m.stream_lanes() });
		expect(within(table).queryByRole('link', { name: /Abschlag c/ })).toBeNull();
		expect(within(table).getByRole('link', { name: /Abschlag s/ })).toBeTruthy();
		const more = within(table).getByRole('button', {
			name: m.stream_more({ count: formatNumber(2) })
		});
		expect(more.getAttribute('aria-expanded')).toBe('false');
		await fireEvent.click(more);
		expect(within(table).getByRole('link', { name: /Abschlag c/ })).toBeTruthy();
		expect(within(table).getByRole('link', { name: /Abschlag e/ })).toBeTruthy();
		expect(within(table).getByRole('button', { name: m.stream_fewer() })).toBeTruthy();
	});
});
