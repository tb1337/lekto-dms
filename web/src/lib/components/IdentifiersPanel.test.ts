import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { session } from '#lib/session.svelte.ts';
import IdentifiersPanel from './IdentifiersPanel.svelte';

const UTILITY = { id: '0199a6c4-0000-7000-8000-0000000000c1', name: 'Stadtwerke Nord' };
const BANK = { id: '0199a6c4-0000-7000-8000-0000000000c2', name: 'Bank' };

const CUSTOMER = {
	kind: 'customer_number',
	value: '20047718',
	written: '2004 7718',
	source: 'learned',
	contacts: [UTILITY],
	documents: 4,
	last: '2026-10-12',
	recommendation: {
		action: 'confirm',
		reason: { code: 'recommend_confirm', params: { count: 4, name: 'Stadtwerke Nord' } }
	}
};
const IBAN = {
	kind: 'iban',
	value: 'DE02120300000000202051',
	written: 'DE02 1203 0000 0000 2020 51',
	source: 'unknown',
	contacts: [UTILITY, BANK],
	documents: 3,
	last: '2026-09-30'
};

const SUGGESTION = {
	kind: 'iban',
	value: 'DE89370400440532013000',
	written: 'DE89 3704 0044 0532 0130 00',
	source: 'suggested',
	contacts: [],
	person: { id: '0199a6c4-0000-7000-8000-0000000000a1', name: 'Max Nord' },
	documents: 6,
	last: '2026-10-31'
};

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
let decisions: unknown[] = [];
let confirmedRecommended = 0;

function json(body: unknown, status = 200) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

beforeEach(() => {
	session.start({
		user: { id: 'admin', username: 'admin', role: 'admin' },
		method: 'password',
		expires_at: '2026-10-14T12:00:00Z',
		csrf_token: 'token'
	});
	decisions = [];
	confirmedRecommended = 0;
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const url = new URL(request.url);
		if (request.method === 'GET' && url.pathname === '/api/v1/identifiers/open') {
			const source = url.searchParams.get('source');
			const advised = url.searchParams.get('recommended') === 'true';
			const items =
				source === 'suggested'
					? [SUGGESTION]
					: [IBAN, CUSTOMER].filter(
							(item) =>
								(!source || item.source === source) && (!advised || 'recommendation' in item)
						);
			return json({
				items,
				total: items.length,
				counts: { learned: 1, unknown: 1, suggested: 1 },
				kinds: { customer_number: 1, iban: 1 },
				recommended: 1,
				to_confirm: confirmedRecommended > 0 ? 0 : 1
			});
		}
		if (request.method === 'GET' && url.pathname === '/api/v1/identifiers/open/detail') {
			return json({
				identifier: CUSTOMER,
				places: [
					{
						document_id: '0199a6c4-0000-7000-8000-0000000000d1',
						title: 'Rechnung Oktober',
						date: '2026-10-12',
						role: 'contact',
						excerpt: { before: 'Kundennummer ', match: '2004 7718', after: ' bitte angeben' }
					}
				]
			});
		}
		if (request.method === 'POST' && url.pathname === '/api/v1/identifiers/open/recommended') {
			confirmedRecommended += 1;
			return json([{ kind: CUSTOMER.kind, value: CUSTOMER.value, done: true, reason: null }]);
		}
		if (request.method === 'POST' && url.pathname === '/api/v1/identifiers/open/decisions') {
			const body = (await request.json()) as { decisions: { kind: string; value: string }[] };
			decisions.push(...body.decisions);
			return json(
				body.decisions.map((item) => ({
					kind: item.kind,
					value: item.value,
					done: true,
					reason: null
				}))
			);
		}
		return json({}, 404);
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	phone.override(null);
	session.clear();
	vi.unstubAllGlobals();
	window.document.body.style.pointerEvents = '';
});

describe('IdentifiersPanel', () => {
	it('lists the open identifiers with where they are open', async () => {
		render(IdentifiersPanel);
		const list = await screen.findByRole('list', { name: m.master_identifiers() });
		const rows = within(list).getAllByRole('listitem');
		expect(rows).toHaveLength(2);
		expect(rows[0].textContent).toContain('DE02 1203 0000 0000 2020 51');
		expect(rows[0].textContent).toContain(m.open_contacts_many({ count: '2' }));
		expect(rows[0].textContent).toContain(m.open_unknown());
		expect(rows[1].textContent).toContain(UTILITY.name);
		expect(rows[1].textContent).toContain(m.open_learned());
		const documents = within(rows[1]).getByRole('link', {
			name: m.open_documents({ count: '4' })
		});
		expect(documents.getAttribute('href')).toContain('fact=customer_number%3A20047718%3A');
	});

	it('says what the documents recommend, why, and shows the recommended alone', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		const list = await screen.findByRole('list', { name: m.master_identifiers() });
		const [iban, customer] = within(list).getAllByRole('listitem');
		expect(customer.textContent).toContain(m.open_advise_confirm());
		// The reason, for a screen reader beside the badge and on hover.
		expect(customer.textContent).toContain('Stadtwerke Nord');
		expect(within(iban).getByLabelText(m.open_advise_none())).toBeTruthy();
		await user.click(screen.getByRole('button', { name: new RegExp(`^${m.open_recommended()}`) }));
		await vi.waitFor(() => {
			const last = fetchMock.mock.calls.at(-1)?.[0];
			expect(new URL(last!.url).searchParams.get('recommended')).toBe('true');
		});
		const shown = await screen.findByRole('list', { name: m.master_identifiers() });
		await vi.waitFor(() => expect(within(shown).getAllByRole('listitem')).toHaveLength(1));
	});

	it('confirms every recommended one at once, after asking with their number', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		const button = await screen.findByRole('button', {
			name: m.open_confirm_recommended({ count: '1' })
		});
		await user.click(button);
		const dialog = await screen.findByRole('alertdialog', {
			name: m.open_confirm_recommended_title({ count: '1' })
		});
		await user.click(
			within(dialog).getByRole('button', { name: m.open_confirm_recommended_do({ count: '1' }) })
		);
		await vi.waitFor(() => expect(confirmedRecommended).toBe(1));
		await vi.waitFor(() =>
			expect(
				screen.queryByRole('button', { name: m.open_confirm_recommended({ count: '1' }) })
			).toBeNull()
		);
		expect(decisions).toEqual([]); // none one by one
	});

	it('loads the list once, and again for other words', async () => {
		const { rerender } = render(IdentifiersPanel);
		await screen.findByRole('list', { name: m.master_identifiers() });
		await new Promise((resolve) => setTimeout(resolve, 600));
		const lists = () =>
			fetchMock.mock.calls.filter(
				([request]) => new URL(request.url).pathname === '/api/v1/identifiers/open'
			);
		expect(lists()).toHaveLength(1);
		await rerender({ query: 'nord' });
		await vi.waitFor(() => expect(lists()).toHaveLength(2));
		expect(new URL(lists()[1][0].url).searchParams.get('q')).toBe('nord');
	});

	it('takes over the chosen ones, leaving out one without a clear contact', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await screen.findByRole('list', { name: m.master_identifiers() });
		await user.click(screen.getByRole('checkbox', { name: m.open_select_all() }));
		const bar = screen.getByRole('region', { name: m.selection_selected({ count: '2' }) });
		expect(bar.textContent).toContain(m.open_skipped_one());
		await user.click(within(bar).getByRole('button', { name: m.open_confirm() }));
		await vi.waitFor(() =>
			expect(decisions).toEqual([{ kind: 'customer_number', value: '20047718', action: 'confirm' }])
		);
		expect(screen.queryByRole('region', { name: /ausgewählt|selected/ })).toBeNull();
	});

	it('rejects all the chosen ones', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await screen.findByRole('list', { name: m.master_identifiers() });
		await user.click(screen.getByRole('checkbox', { name: m.open_select({ value: '20047718' }) }));
		await user.click(screen.getByRole('button', { name: m.open_reject() }));
		await vi.waitFor(() =>
			expect(decisions).toEqual([{ kind: 'customer_number', value: '20047718', action: 'reject' }])
		);
	});

	it('opens one with where it stands and takes it over', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await screen.findByRole('list', { name: m.master_identifiers() });
		await user.click(screen.getByRole('button', { name: m.open_open({ value: '20047718' }) }));
		const dialog = await screen.findByRole('dialog');
		expect(await within(dialog).findByText('2004 7718')).toBeTruthy();
		expect(dialog.textContent).toContain('Rechnung Oktober');
		await user.click(within(dialog).getByRole('button', { name: m.open_confirm() }));
		await vi.waitFor(() =>
			expect(decisions).toEqual([
				{ kind: 'customer_number', value: '20047718', action: 'confirm', contact_id: null }
			])
		);
	});

	it('narrows to the learned ones', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await screen.findByRole('list', { name: m.master_identifiers() });
		await user.click(screen.getByRole('button', { name: new RegExp(`^${m.open_learned()}`) }));
		await vi.waitFor(() =>
			expect(
				within(screen.getByRole('list', { name: m.master_identifiers() })).getAllByRole('listitem')
			).toHaveLength(1)
		);
	});

	it('shows a suggestion for a profile and takes it over there', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await screen.findByRole('list', { name: m.master_identifiers() });
		await user.click(screen.getByRole('button', { name: new RegExp(`^${m.open_suggestions()}`) }));
		await vi.waitFor(() => expect(screen.getByText(m.open_column_target())).toBeTruthy());
		const list = screen.getByRole('list', { name: m.master_identifiers() });
		const [row] = within(list).getAllByRole('listitem');
		expect(row.textContent).toContain('Max Nord');
		expect(row.textContent).toContain(m.open_target_profile());
		expect(row.textContent).toContain(m.open_suggested());
		await user.click(
			within(row).getByRole('button', { name: m.open_open({ value: SUGGESTION.written }) })
		);
		const dialog = await screen.findByRole('dialog');
		await user.click(
			within(dialog).getByRole('button', { name: m.open_confirm_profile({ person: 'Max Nord' }) })
		);
		await vi.waitFor(() =>
			expect(decisions).toEqual([
				{ kind: 'iban', value: SUGGESTION.value, action: 'confirm', contact_id: null }
			])
		);
	});
});
