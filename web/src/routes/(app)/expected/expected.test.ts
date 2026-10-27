import { render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { formatDate } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import Page from './+page.svelte';

type Expected = components['schemas']['ExpectedOut'];

const series = (state: Expected['state'], changes: Partial<Expected> = {}): Expected => ({
	contact: { id: 'c1', name: 'Stadtwerke' },
	document_type: { id: 't1', name: 'Abschlag' },
	number: { kind: 'contract_number', value: 'V-1' },
	cadence: 'monthly',
	interval_days: 31,
	spread_days: 2,
	documents: 3,
	last: { id: 'd3', title: 'Abschlag September', document_date: '2026-09-15' },
	next_date: '2026-10-15',
	next_period: '2026-10',
	state,
	...changes
});

describe('Erwartet', () => {
	beforeEach(() => {
		session.start({
			user: { id: 'u1', username: 'tobi', role: 'user' },
			method: 'password',
			expires_at: '2026-10-21T12:00:00Z',
			csrf_token: 'token'
		} as never);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the series in their sections with rhythm, spread and the last document', async () => {
		const api = fakeApi({
			'GET /api/v1/expected': () => [
				series('overdue'),
				series('later', {
					contact: { id: 'c2', name: 'Versicherung' },
					number: null,
					cadence: 'days',
					interval_days: 14
				})
			]
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		const overdue = await screen.findByRole('region', { name: new RegExp(m.expected_overdue()) });
		expect(within(overdue).getByText(/V-1$/)).toBeTruthy(); // with its kind
		expect(
			within(overdue).getByText(m.expected_next({ date: formatDate('2026-10-15') }))
		).toBeTruthy();
		expect(
			within(overdue).getByText(
				`${m.expected_monthly()} · ${m.expected_spread({ count: '2' })} · ${m.expected_documents({ count: '3' })}`
			)
		).toBeTruthy();
		expect(within(overdue).getByRole('link', { name: 'Abschlag September' })).toBeTruthy();
		expect(within(overdue).getByText(m.expected_for({ period: '2026-10' }))).toBeTruthy();
		const later = screen.getByRole('region', { name: new RegExp(m.expected_later()) });
		expect(
			within(later).getByText(new RegExp(m.expected_every_days({ count: '14' })))
		).toBeTruthy();
		expect(screen.queryByRole('region', { name: new RegExp(m.expected_ended()) })).toBeNull();
		// Overdue as the day is in the browser's time zone.
		const zone = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);
		expect(calls(api)).toContain(`GET /api/v1/expected?tz=${zone}`);
	});

	it('says so when there is no series', async () => {
		vi.stubGlobal('fetch', fakeApi({ 'GET /api/v1/expected': () => [] }));
		render(Page);
		expect(await screen.findByText(m.expected_none())).toBeTruthy();
	});
});
