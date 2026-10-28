import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { formatDate } from '#lib/i18n.ts';
import { inbox } from '#lib/inbox.svelte.ts';
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

const JOBS = {
	kinds: [
		{ kind: 'contacts.logo', running: 0, due: 3, planned: 0, failed: 2, done: 10 },
		{ kind: 'documents.index', running: 1, due: 0, planned: 0, failed: 0, done: 40 }
	],
	last_started_at: '2026-10-27T11:59:56Z',
	now: '2026-10-27T12:00:00Z',
	kept_since: '2026-10-20T12:00:00Z'
};

function signIn(role: 'admin' | 'user') {
	session.start({
		user: { id: 'u1', username: 'tobi', role },
		method: 'password',
		expires_at: '2026-10-28T12:00:00Z',
		csrf_token: 'token'
	} as never);
}

function routes(expected: Expected[] = []) {
	return fakeApi({
		'GET /api/v1/expected': () => expected,
		'GET /api/v1/jobs/summary': () => JOBS,
		'GET /api/v1/identifiers/open/summary': () => ({ learned: 31, unknown: 17, suggested: 0 })
	});
}

afterEach(() => {
	inbox.summary = null;
	session.clear();
	vi.unstubAllGlobals();
});

describe('Übersicht', () => {
	it('shows the inbox, the identifiers and the jobs to an admin', async () => {
		signIn('admin');
		vi.stubGlobal('fetch', routes());
		inbox.summary = {
			new: 3,
			review: 7,
			intervene: 2,
			processing: 1,
			done: 4,
			open: 13,
			worst_lane: 'red'
		};
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: m.overview_title() })).toBeTruthy();
		const tile = screen.getByRole('region', { name: m.nav_inbox() });
		expect(tile.textContent).toContain(`2 ${m.lane_red()}`);
		expect(tile.textContent).toContain(`7 ${m.lane_yellow()}`);
		expect(tile.textContent).toContain(m.overview_processing({ count: '1' }));
		expect(within(tile).getByRole('link', { name: m.overview_inbox_go() })).toBeTruthy();

		const identifiers = screen.getByRole('region', { name: m.master_identifiers() });
		expect(await within(identifiers).findByText('48')).toBeTruthy();
		expect(identifiers.textContent).toContain(m.overview_identifiers_learned({ count: '31' }));
		expect(
			within(identifiers)
				.getByRole('link', { name: m.overview_identifiers_go() })
				.getAttribute('href')
		).toBe('/ui/admin/master-data?tab=identifiers');

		const system = screen.getByRole('region', { name: m.nav_system() });
		expect(await within(system).findByText(m.overview_jobs_failed())).toBeTruthy();
		expect(system.textContent).toContain(m.overview_jobs_due({ count: '3' }));
	});

	it('leaves the identifiers to admins', async () => {
		signIn('user');
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(Page);
		expect(await screen.findByText(m.overview_jobs_failed())).toBeTruthy();
		expect(screen.queryByRole('region', { name: m.master_identifiers() })).toBeNull();
		expect(calls(api).some((call) => call.includes('/identifiers/'))).toBe(false);
	});

	it('shows what is expected soon, the rest on request', async () => {
		signIn('user');
		const api = routes([
			series('overdue'),
			series('later', {
				contact: { id: 'c2', name: 'Versicherung' },
				number: null,
				cadence: 'days',
				interval_days: 14
			})
		]);
		vi.stubGlobal('fetch', api);
		render(Page);
		const overdue = await screen.findByRole('region', { name: new RegExp(m.expected_overdue()) });
		expect(within(overdue).getByText(/V-1$/)).toBeTruthy();
		expect(
			within(overdue).getByText(m.expected_next({ date: formatDate('2026-10-15') }))
		).toBeTruthy();
		expect(within(overdue).getByRole('link', { name: 'Abschlag September' })).toBeTruthy();
		expect(screen.queryByRole('region', { name: new RegExp(m.expected_later()) })).toBeNull();
		await userEvent.click(
			screen.getByRole('button', { name: m.overview_expected_more({ count: '1' }) })
		);
		const later = screen.getByRole('region', { name: new RegExp(m.expected_later()) });
		expect(
			within(later).getByText(new RegExp(m.expected_every_days({ count: '14' })))
		).toBeTruthy();
		const zone = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);
		expect(calls(api)).toContain(`GET /api/v1/expected?tz=${zone}`);
	});

	it('says so when there is no series', async () => {
		signIn('user');
		vi.stubGlobal('fetch', routes([]));
		render(Page);
		expect(await screen.findByText(m.expected_none())).toBeTruthy();
	});
});
