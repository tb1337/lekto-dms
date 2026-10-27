// The page of a webhook: its deliveries as a table with pages, by outcome and event.
import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import { goTo } from '#lib/testing/page-state.svelte.ts';
import { choose } from '#lib/testing/select.ts';
import Page from './+page.svelte';

type Delivery = components['schemas']['DeliveryOut'];

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

const webhook = {
	id: 'hook',
	owner_id: 'u1',
	name: 'Test',
	url: 'https://node.example/lekto',
	event_types: ['*'],
	active: true,
	signed: true,
	headers: [],
	body: 'thin',
	body_template: null,
	max_open_tasks: 4,
	model_call: null,
	disabled_reason: null,
	failed_streak: 0,
	previous_secret_valid_until: null,
	created_at: '2026-10-25T10:00:00Z',
	updated_at: '2026-10-25T10:00:00Z'
};

const delivery = (changes: Partial<Delivery>): Delivery => ({
	id: 'd1',
	webhook_id: 'hook',
	event_id: 'e1',
	event_type: 'document.filed',
	document_id: 'doc1',
	attempt: 1,
	started_at: '2026-10-27T08:15:59Z',
	duration_ms: 48,
	outcome: 'delivered',
	status_code: 200,
	error: null,
	next_attempt_at: null,
	document: { id: 'doc1', title: 'Stadtwerke – Abschlag' },
	document_hidden: false,
	...changes
});

const summary = {
	delivered: 72,
	retrying: 1,
	gave_up: 3,
	dropped: 1,
	event_types: ['document.filed', 'webhook.test'],
	kept_since: '2026-10-20T08:00:00Z'
};

// A page of the log; 77 entries in all unless said otherwise.
const page = (items: Delivery[], total = 77) => ({ items, total, next_offset: null });

function routes() {
	return fakeApi({
		'GET /api/v1/webhooks/hook': () => webhook,
		'GET /api/v1/webhooks/hook/deliveries/summary': () => summary,
		'GET /api/v1/webhooks/hook/deliveries': () =>
			page([
				delivery({}),
				delivery({
					id: 'd2',
					event_type: 'document.deleted',
					attempt: 6,
					outcome: 'gave_up',
					status_code: null,
					error: 'no answer within 10 seconds',
					document: null,
					document_hidden: true
				}),
				delivery({
					id: 'd3',
					event_type: 'webhook.test',
					document_id: null,
					document: null
				})
			])
	});
}

describe('the page of a webhook', () => {
	beforeEach(() => {
		session.start({
			user: { id: 'u1', username: 'tobi', role: 'user' },
			method: 'password',
			expires_at: '2026-10-28T12:00:00Z',
			csrf_token: 'token'
		} as never);
		goTo('/ui/webhooks/hook', { id: 'hook' });
	});

	afterEach(() => {
		session.clear();
		vi.unstubAllGlobals();
		localStorage.clear();
	});

	it('shows the deliveries with their documents, counted by outcome', async () => {
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(Page);
		const table = await screen.findByRole('table');
		const rows = within(table).getAllByRole('row');
		expect(within(rows[1]).getByText(m.event_filed())).toBeTruthy();
		expect(within(rows[1]).getByRole('link', { name: 'Stadtwerke – Abschlag' })).toBeTruthy();
		expect(within(rows[2]).getByText(m.jobs_hidden_document())).toBeTruthy();
		expect(within(rows[2]).getByText(m.delivery_attempt({ attempt: 6 }))).toBeTruthy();
		expect(within(table).getByText('no answer within 10 seconds')).toBeTruthy();
		expect(within(table).getByText(m.event_test())).toBeTruthy();
		expect(
			screen.getByRole('button', { name: new RegExp(`^${m.delivery_view_problems()}`) }).textContent
		).toContain('5');
		expect(screen.getByText(/1 – 25 (von|of) 77/)).toBeTruthy();
		expect(calls(api)).toContain('GET /api/v1/webhooks/hook/deliveries?offset=0&limit=25');
	});

	it('narrows the deliveries to the problems and to one event', async () => {
		const api = routes();
		vi.stubGlobal('fetch', api);
		render(Page);
		await screen.findByRole('table');
		await userEvent.click(
			screen.getByRole('button', { name: new RegExp(`^${m.delivery_view_problems()}`) })
		);
		await vi.waitFor(() =>
			expect(calls(api)).toContain(
				'GET /api/v1/webhooks/hook/deliveries?outcome=retrying&outcome=gave_up&outcome=dropped&offset=0&limit=25'
			)
		);
		await choose(
			userEvent.setup(),
			screen.getByRole('combobox', { name: m.delivery_event() }),
			'webhook.test'
		);
		await vi.waitFor(() =>
			expect(calls(api)).toContain(
				'GET /api/v1/webhooks/hook/deliveries/summary?event_type=webhook.test'
			)
		);
		expect(calls(api)).toContain(
			'GET /api/v1/webhooks/hook/deliveries?outcome=retrying&outcome=gave_up&outcome=dropped&event_type=webhook.test&offset=0&limit=25'
		);
	});

	it('says so when the choice leaves no delivery', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/webhooks/hook': () => webhook,
				'GET /api/v1/webhooks/hook/deliveries/summary': () => summary,
				'GET /api/v1/webhooks/hook/deliveries': (_request, url) =>
					url.searchParams.has('outcome') ? page([], 0) : page([delivery({})], 1)
			})
		);
		render(Page);
		await screen.findByRole('table');
		await userEvent.click(
			screen.getByRole('button', { name: new RegExp(`^${m.delivery_view_problems()}`) })
		);
		expect(await screen.findByText(m.delivery_none_chosen())).toBeTruthy();
	});
});
