// The tab "Jobs": counts, the open jobs of a kind, the failed ones tried again by an admin.
import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '#lib/jobs.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi } from '#lib/testing/documents.ts';
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
});

describe('the jobs tab', () => {
	it('counts the jobs and opens the jobs of a kind', async () => {
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(JobsTab);
		expect(await screen.findByText(m.jobs_worker_active())).toBeTruthy();
		const group = screen.getByRole('button', { name: /Verarbeitungsschritt|Processing step/ });
		expect(group.getAttribute('aria-expanded')).toBe('false');
		expect(screen.queryByRole('button', { name: /Logo/ })).toBeNull(); // nothing open
		await userEvent.click(group);
		expect(await screen.findByText('Stadtwerke – Abschlag')).toBeTruthy();
		expect(screen.getByText(m.jobs_hidden_document())).toBeTruthy();
		expect(group.getAttribute('aria-expanded')).toBe('true');
		expect(calls(api)).toContain(
			'GET /api/v1/jobs?state=running&state=due&state=planned&kind=pipeline.node&offset=0&limit=20'
		);
		expect(screen.getByRole('button', { name: m.load_more() })).toBeTruthy();
	});

	it('lets an admin try a failed job again, a failed step at its document', async () => {
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(JobsTab);
		await userEvent.click(
			await screen.findByRole('button', { name: new RegExp(m.jobs_view_failed()) })
		);
		const logo = (await screen.findByText('Stadtwerke')).closest('li') as HTMLElement;
		expect(within(logo).getByText('timeout')).toBeTruthy();
		await userEvent.click(within(logo).getByRole('button', { name: m.jobs_retry() }));
		const step = screen.getByText('Stadtwerke – Abschlag').closest('li') as HTMLElement;
		await userEvent.click(within(step).getByRole('button', { name: m.jobs_retry() }));
		const posts = calls(api).filter((call) => call.startsWith('POST'));
		expect(posts).toEqual(['POST /api/v1/jobs/f2/retry', 'POST /api/v1/documents/d1/retry']);
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
	});

	it('warns when jobs are due and no worker took one for a while', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/jobs/summary': () => ({ ...summary, last_started_at: '2026-10-24T11:50:00Z' })
			})
		);
		render(JobsTab);
		expect(await screen.findByText(m.jobs_worker_stale())).toBeTruthy();
	});
});
