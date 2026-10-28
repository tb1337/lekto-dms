// The tab "Maintenance": the actions over the documents with their waiting jobs, run by admins
// after a question.
import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { toast } from 'svelte-sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import MaintenanceTab from './MaintenanceTab.svelte';

const summary = {
	kinds: [
		{ kind: 'pipeline.relate', running: 1, due: 41, planned: 0, failed: 0, done: 12 },
		{ kind: 'contacts.logo', running: 0, due: 0, planned: 0, failed: 1, done: 41 }
	],
	last_started_at: '2026-10-24T11:59:58Z',
	now: '2026-10-24T12:00:00Z',
	kept_since: '2026-10-17T12:00:00Z'
};

function routes(logoFetch = true) {
	return fakeApi({
		'GET /api/v1/jobs/summary': () => summary,
		'GET /api/v1/pipeline': () => ({
			nodes: [],
			vision: null,
			logo_fetch: logoFetch,
			meaning_search: false
		}),
		'POST /api/v1/pipeline/relate': () => ({ queued: 1284 }),
		'POST /api/v1/pipeline/read-facts': () => ({ queued: 0 }),
		'POST /api/v1/pipeline/render-pages': () => ({ queued: 1 })
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
	vi.restoreAllMocks();
});

describe('the maintenance tab', () => {
	it('names the actions with their waiting jobs and queues one after a question', async () => {
		const success = vi.spyOn(toast, 'success');
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(MaintenanceTab);
		const relate = (await screen.findByText(m.maintenance_relate_name())).closest(
			'li'
		) as HTMLElement;
		expect(within(relate).getByText(m.maintenance_waiting({ count: '42' }))).toBeTruthy();
		const pages = screen.getByText(m.maintenance_pages_name()).closest('li') as HTMLElement;
		expect(within(pages).getByText(m.maintenance_waiting_none())).toBeTruthy();
		await userEvent.click(within(relate).getByRole('button', { name: m.maintenance_run() }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain(m.maintenance_relate_confirm());
		expect(calls(api)).not.toContain('POST /api/v1/pipeline/relate');
		await userEvent.click(within(dialog).getByRole('button', { name: m.maintenance_run() }));
		await waitFor(() => expect(calls(api)).toContain('POST /api/v1/pipeline/relate'));
		await waitFor(() =>
			expect(success).toHaveBeenCalledWith(m.maintenance_queued_documents({ count: '1,284' }))
		);
	});

	it('says when there was nothing to queue, and when one document was', async () => {
		const success = vi.spyOn(toast, 'success');
		vi.stubGlobal('fetch', routes());
		render(MaintenanceTab);
		const facts = (await screen.findByText(m.maintenance_facts_name())).closest(
			'li'
		) as HTMLElement;
		await userEvent.click(within(facts).getByRole('button', { name: m.maintenance_run() }));
		const dialog = await screen.findByRole('alertdialog');
		await userEvent.click(within(dialog).getByRole('button', { name: m.maintenance_run() }));
		await waitFor(() => expect(success).toHaveBeenCalledWith(m.maintenance_queued_none()));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		// The closed dialog still holds the page's pointer events for a moment.
		const user = userEvent.setup({ pointerEventsCheck: 0 });
		const pages = screen.getByText(m.maintenance_pages_name()).closest('li') as HTMLElement;
		await user.click(within(pages).getByRole('button', { name: m.maintenance_run() }));
		await user.click(
			within(await screen.findByRole('alertdialog')).getByRole('button', {
				name: m.maintenance_run()
			})
		);
		await waitFor(() => expect(success).toHaveBeenCalledWith(m.maintenance_queued_document_one()));
	});

	it('holds the logos back while Lekto does not fetch them', async () => {
		vi.stubGlobal('fetch', routes(false));
		render(MaintenanceTab);
		const logos = (await screen.findByText(m.maintenance_logos_name())).closest(
			'li'
		) as HTMLElement;
		expect(await within(logos).findByText(m.maintenance_logos_off())).toBeTruthy();
		expect(within(logos).getByRole('button', { name: m.maintenance_run() })).toHaveProperty(
			'disabled',
			true
		);
	});

	it('shows a user the rows without buttons', async () => {
		signIn('user');
		vi.stubGlobal('fetch', routes());
		render(MaintenanceTab);
		expect(await screen.findByText(m.maintenance_relate_name())).toBeTruthy();
		expect(screen.getByText(m.maintenance_admins_only())).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.maintenance_run() })).toBeNull();
	});
});
