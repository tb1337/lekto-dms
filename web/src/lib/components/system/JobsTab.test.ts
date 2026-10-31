// The tab "Jobs": counts, the jobs as a table with pages, the failed ones tried again by an admin.
import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '#lib/jobs.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import { choose } from '#lib/testing/select.ts';
import JobsTab from './JobsTab.svelte';

const summary = {
	kinds: [
		{ kind: 'contacts.logo', running: 0, due: 0, planned: 0, failed: 1, done: 41 },
		{ kind: 'pipeline.node', running: 1, due: 3, planned: 0, failed: 1, done: 900 }
	],
	last_started_at: '2026-10-24T11:59:58Z',
	now: '2026-10-24T12:00:00Z',
	kept_since: '2026-10-17T12:00:00Z'
};

function job(overrides: Partial<Job>): Job {
	return {
		id: 'j1',
		kind: 'pipeline.node',
		state: 'running',
		attempts: 1,
		run_at: '2026-10-24T11:59:00Z',
		started_at: '2026-10-24T11:59:46Z',
		finished_at: null,
		document: { id: 'd1', title: 'Stadtwerke – Abschlag' },
		document_hidden: false,
		node: 'ocr',
		contact: null,
		error: null,
		retry: null,
		...overrides
	};
}

const failedStep = job({
	id: 'f1',
	state: 'failed',
	finished_at: '2026-10-24T09:12:00Z',
	error: 'page 3 unreadable',
	retry: 'document'
});
const failedLogo = job({
	id: 'f2',
	kind: 'contacts.logo',
	state: 'failed',
	node: null,
	document: null,
	contact: 'Stadtwerke',
	finished_at: '2026-10-24T09:12:00Z',
	error: 'timeout',
	retry: 'job'
});

function routes() {
	return fakeApi({
		'GET /api/v1/jobs/summary': () => summary,
		'GET /api/v1/jobs/durations': () => ({
			kinds: [
				{
					kind: 'pipeline.node',
					count: 900,
					wait_median_ms: 360000,
					wait_p90_ms: 900000,
					run_median_ms: 9000,
					run_p90_ms: 41000
				}
			],
			since: '2026-10-17T12:00:00Z'
		}),
		'GET /api/v1/jobs': (_request, url) =>
			url.searchParams.getAll('state').includes('failed')
				? { items: [failedStep, failedLogo], total: 2, next_offset: null }
				: {
						items: [job({}), job({ id: 'j2', document: null, document_hidden: true })],
						total: 4,
						next_offset: 2
					},
		'POST /api/v1/jobs/f2/retry': () => ({ ...failedLogo, state: 'due', retry: null }),
		'POST /api/v1/documents/d1/retry': () => ({})
	});
}

function signIn(role: 'admin' | 'user') {
	session.start({
		user: { id: role, username: role, role },
		method: 'password',
		expires_at: '2026-10-25T12:00:00Z',
		csrf_token: 'token'
	});
}

beforeEach(() => signIn('admin'));

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
	localStorage.clear();
});

describe('the jobs tab', () => {
	it('counts the jobs and lists the open ones as a table, what runs next on top', async () => {
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(JobsTab);
		expect(await screen.findByText(m.jobs_worker_active())).toBeTruthy();
		const table = await screen.findByRole('table');
		const rows = within(table).getAllByRole('row');
		expect(rows).toHaveLength(3); // the header and two jobs
		// The title shows the document in the Beam; into it from there.
		expect(
			within(rows[1]).getByRole('button', {
				name: m.beam_open_named({ title: 'Stadtwerke – Abschlag' })
			})
		).toBeTruthy();
		expect(within(rows[1]).queryByRole('link')).toBeNull();
		expect(within(rows[1]).getByText(m.jobs_state_running())).toBeTruthy();
		expect(within(rows[2]).getByText(m.jobs_hidden_document())).toBeTruthy();
		expect(calls(api)).toContain(
			'GET /api/v1/jobs?state=running&state=due&state=planned&offset=0&limit=25'
		);
		expect(screen.getByText(/1 – 4 (von|of) 4/)).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.jobs_retry() })).toBeNull();
	});

	it('shows as many jobs to a page as this browser last chose', async () => {
		localStorage.setItem('lekto.page-size.jobs', '100');
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(JobsTab);
		await screen.findByRole('table');
		expect(calls(api)).toContain(
			'GET /api/v1/jobs?state=running&state=due&state=planned&offset=0&limit=100'
		);
	});

	it('filters by kind and turns the pages', async () => {
		const api = fakeApi({
			'GET /api/v1/jobs/summary': () => summary,
			'GET /api/v1/jobs': (_request, url) => ({
				items: [job({ id: `p${url.searchParams.get('offset')}` })],
				total: 120,
				next_offset: null
			})
		});
		vi.stubGlobal('fetch', api);
		render(JobsTab);
		await screen.findByRole('table');
		await choose(
			userEvent.setup(),
			screen.getByRole('combobox', { name: m.jobs_kind() }),
			'contacts.logo'
		);
		await userEvent.click(
			await screen.findByRole('button', { name: m.pagination_page({ page: '2' }) })
		);
		expect(await screen.findByText(/26 – 50 (von|of) 120/)).toBeTruthy();
		expect(calls(api)).toContain(
			'GET /api/v1/jobs?state=running&state=due&state=planned&kind=contacts.logo&offset=25&limit=25'
		);
	});

	it('lets an admin try a failed job again, a failed step at its document', async () => {
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(JobsTab);
		await userEvent.click(
			await screen.findByRole('button', { name: new RegExp(m.jobs_view_failed()) })
		);
		const logo = (await screen.findByText('Stadtwerke')).closest('tr') as HTMLElement;
		expect(screen.getByText('timeout')).toBeTruthy();
		await userEvent.click(within(logo).getByRole('button', { name: m.jobs_retry() }));
		const step = screen.getByText('Stadtwerke – Abschlag').closest('tr') as HTMLElement;
		await userEvent.click(within(step).getByRole('button', { name: m.jobs_retry() }));
		const posts = calls(api).filter((call) => call.startsWith('POST'));
		expect(posts).toEqual(['POST /api/v1/jobs/f2/retry', 'POST /api/v1/documents/d1/retry']);
	});

	it('shows the done jobs with their times and how long each kind takes', async () => {
		const api = fakeApi({
			'GET /api/v1/jobs/summary': () => summary,
			'GET /api/v1/jobs/durations': () => ({
				kinds: [
					{
						kind: 'pipeline.node',
						count: 900,
						wait_median_ms: 360000,
						wait_p90_ms: 900000,
						run_median_ms: 9000,
						run_p90_ms: 41000
					}
				],
				since: '2026-10-17T12:00:00Z'
			}),
			'GET /api/v1/jobs': () => ({
				items: [
					job({
						id: 'd1',
						state: 'done',
						started_at: '2026-10-24T11:59:03Z',
						finished_at: '2026-10-24T11:59:05Z'
					})
				],
				total: 1,
				next_offset: null
			})
		});
		vi.stubGlobal('fetch', api);
		render(JobsTab);
		await userEvent.click(
			await screen.findByRole('button', { name: new RegExp(m.jobs_view_done()) })
		);
		expect(await screen.findByText(m.jobs_durations_title())).toBeTruthy();
		const [jobs, kinds] = screen.getAllByRole('table');
		const cells = within(jobs)
			.getAllByRole('cell')
			.map((cell) => cell.textContent?.trim());
		expect(cells).toContain('3s'); // waited
		expect(cells).toContain('2s'); // ran
		expect(within(kinds).getByText('900')).toBeTruthy();
		expect(calls(api)).toContain('GET /api/v1/jobs?state=done&offset=0&limit=25');
	});

	it('shows a user the failed jobs without errors or retries', async () => {
		signIn('user');
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/jobs/summary': () => summary,
				'GET /api/v1/jobs': () => ({
					items: [{ ...failedLogo, error: null, retry: null }],
					total: 1,
					next_offset: null
				})
			})
		);
		render(JobsTab);
		await userEvent.click(
			await screen.findByRole('button', { name: new RegExp(m.jobs_view_failed()) })
		);
		expect(await screen.findByText('Stadtwerke')).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.jobs_retry() })).toBeNull();
		expect(screen.queryByText(m.jobs_last_error())).toBeNull();
		expect(screen.getByRole('columnheader', { name: m.jobs_col_failed_at() })).toBeTruthy();
	});

	it('warns when jobs are due and no worker took one for a while', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/jobs/summary': () => ({ ...summary, last_started_at: '2026-10-24T11:50:00Z' }),
				'GET /api/v1/jobs': () => ({ items: [], total: 0, next_offset: null })
			})
		);
		render(JobsTab);
		expect(await screen.findByText(m.jobs_worker_stale())).toBeTruthy();
	});
});
