import { cleanup, render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usageLabel } from '#lib/components/UsageCount.svelte';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { session } from '#lib/session.svelte.ts';
import { fakeBack, goTo, testPage } from '#lib/testing/page-state.svelte.ts';
import IdentifiersPanel from './IdentifiersPanel.svelte';

vi.mock('$app/navigation', async () => ({
	beforeNavigate: vi.fn(),
	goto: (await import('#lib/testing/page-state.svelte.ts')).fakeGoto
}));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

const UTILITY = { id: '0199a6c4-0000-7000-8000-0000000000c1', name: 'Stadtwerke Nord' };
const LOGO = `/api/v1/contacts/${UTILITY.id}/logo`;
const BANK = { id: '0199a6c4-0000-7000-8000-0000000000c2', name: 'Bank' };

const CUSTOMER = {
	kind: 'customer_number',
	value: '20047718',
	ref: 'MjAwNDc3MTg',
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
	ref: 'REUwMg',
	written: 'DE02 1203 0000 0000 2020 51',
	source: 'unknown',
	contacts: [UTILITY, BANK],
	documents: 3,
	last: '2026-09-30'
};

const SUGGESTION = {
	kind: 'iban',
	value: 'DE89370400440532013000',
	ref: 'REU4OQ',
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
	goTo('/ui/admin/master-data?tab=identifiers');
	vi.spyOn(history, 'back').mockImplementation(fakeBack);
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
		const searched =
			request.method === 'POST' && url.pathname === '/api/v1/identifiers/open/search';
		if ((request.method === 'GET' && url.pathname === '/api/v1/identifiers/open') || searched) {
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
		if (request.method === 'GET' && url.pathname === '/api/v1/contacts') {
			return json([
				{
					...UTILITY,
					logo: { url: LOGO, source: 'uploaded', domain: null, stored_at: '2026-10-01T00:00:00Z' }
				},
				BANK
			]);
		}
		const detailed = [CUSTOMER, IBAN, SUGGESTION].find(
			(item) => url.pathname === `/api/v1/identifiers/open/${item.kind}/${item.ref}`
		);
		if (request.method === 'GET' && detailed && detailed !== CUSTOMER) {
			return json({ identifier: detailed, places: [] });
		}
		if (request.method === 'GET' && detailed === CUSTOMER) {
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
	vi.useRealTimers();
	window.document.body.style.pointerEvents = '';
});

/** The rows of the table (wider than a phone), its head left out. */
async function rows() {
	const table = await screen.findByRole('table', { name: m.master_identifiers() });
	return within(table).getAllByRole('row').slice(1);
}

describe('IdentifiersPanel', () => {
	it('lists the open identifiers with where they are open, the contact with its logo', async () => {
		render(IdentifiersPanel);
		const found = await rows();
		expect(found).toHaveLength(2);
		expect(found[0].textContent).toContain('DE02 1203 0000 0000 2020 51');
		expect(found[0].textContent).toContain(m.open_contacts_many({ count: '2' }));
		expect(found[0].textContent).toContain(m.open_unknown());
		expect(found[1].textContent).toContain(UTILITY.name);
		expect(found[1].textContent).toContain(m.open_learned());
		const documents = within(found[1]).getByRole('link', {
			name: usageLabel(4)
		});
		// The value by its reference, never as written.
		expect(documents.getAttribute('href')).toContain('fact=customer_number%3AMjAwNDc3MTg%3A');
		// The logo comes from the contacts, which the list does not carry.
		await vi.waitFor(() => expect(found[1].querySelector('img')?.getAttribute('src')).toBe(LOGO));
		expect(found[0].querySelector('img')).toBeNull();
	});

	it('opens one from its whole row on a phone, and chooses it while some are chosen', async () => {
		phone.override(true);
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await screen.findByRole('list', { name: m.master_identifiers() });
		const customer = () => screen.getByRole('button', { name: m.open_open({ value: '20047718' }) });
		expect(customer().textContent).toContain('20047718');
		await user.click(
			screen.getByRole('checkbox', { name: m.open_select({ value: IBAN.written }) })
		);
		screen.getByRole('region', { name: m.selection_selected({ count: '1' }) });
		// Chosen: the rows choose, the dialog waits.
		await user.click(screen.getByRole('button', { name: m.open_select({ value: '20047718' }) }));
		screen.getByRole('region', { name: m.selection_selected({ count: '2' }) });
		expect(screen.queryByRole('dialog')).toBeNull();
		await user.click(screen.getByRole('button', { name: m.open_selection_clear() }));
		await user.click(customer());
		expect(await screen.findByRole('dialog')).toBeTruthy();
	});

	it('says what the documents recommend, why, and shows the recommended alone', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		const [iban, customer] = await rows();
		expect(customer.textContent).toContain(m.open_advise_confirm());
		// The reason, for a screen reader beside the badge and on hover; the badge's trigger
		// takes the focus.
		expect(customer.textContent).toContain('Stadtwerke Nord');
		expect(
			within(customer).getByRole('button', { name: new RegExp(m.open_advise_confirm()) }).tagName
		).toBe('BUTTON');
		expect(within(iban).getByText(m.open_advise_none())).toBeTruthy();
		await user.click(screen.getByRole('button', { name: new RegExp(`^${m.open_recommended()}`) }));
		await vi.waitFor(() => {
			const last = fetchMock.mock.calls.at(-1)?.[0];
			expect(new URL(last!.url).searchParams.get('recommended')).toBe('true');
		});
		await vi.waitFor(async () => expect(await rows()).toHaveLength(1));
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
		// The clock is faked so the wait after the last key passes at once.
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const { rerender } = render(IdentifiersPanel);
		await rows();
		await vi.advanceTimersByTimeAsync(600);
		const lists = () =>
			fetchMock.mock.calls.filter(([request]) =>
				new URL(request.url).pathname.startsWith('/api/v1/identifiers/open')
			);
		expect(lists()).toHaveLength(1);
		await rerender({ query: 'nord' });
		await vi.advanceTimersByTimeAsync(250);
		await vi.waitFor(() => expect(lists()).toHaveLength(2));
		// The words go in the body, never in the address.
		const [request] = lists()[1];
		expect(new URL(request.url).pathname).toBe('/api/v1/identifiers/open/search');
		expect(new URL(request.url).searchParams.has('q')).toBe(false);
		expect(await request.clone().json()).toEqual({ q: 'nord' });
	});

	it('takes over the chosen ones, leaving out one without a clear contact', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await rows();
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
		await rows();
		await user.click(screen.getByRole('checkbox', { name: m.open_select({ value: '20047718' }) }));
		await user.click(screen.getByRole('button', { name: m.open_reject() }));
		await vi.waitFor(() =>
			expect(decisions).toEqual([{ kind: 'customer_number', value: '20047718', action: 'reject' }])
		);
	});

	it('opens one with where it stands and takes it over', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await rows();
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

	it('keeps the dialog in the history entry, and opens a place in the Beam', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await rows();
		await user.click(screen.getByRole('button', { name: m.open_open({ value: '20047718' }) }));
		const dialog = await screen.findByRole('dialog');
		// The address names nothing; the entry holds the identifier by its reference.
		expect(testPage.url.search).toBe('?tab=identifiers');
		expect(testPage.state.identifier).toEqual({ kind: 'customer_number', ref: CUSTOMER.ref });
		await user.click(
			await within(dialog).findByRole('button', {
				name: m.beam_open_named({ title: 'Rechnung Oktober' })
			})
		);
		expect(testPage.state.beam).toMatchObject({
			ids: ['0199a6c4-0000-7000-8000-0000000000d1'],
			index: 0,
			source: { kind: 'open', identifier: 'customer_number', ref: CUSTOMER.ref }
		});
		// Back: first the Beam, then the dialog.
		history.back();
		expect(testPage.state.beam).toBeUndefined();
		expect(testPage.state.identifier).toBeTruthy();
		history.back();
		await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
	});

	it('opens the dialog a reload brings back, and closes it when it is decided meanwhile', async () => {
		goTo(
			'/ui/admin/master-data?tab=identifiers',
			{},
			{
				identifier: { kind: 'customer_number', ref: CUSTOMER.ref }
			}
		);
		render(IdentifiersPanel);
		const dialog = await screen.findByRole('dialog');
		expect(await within(dialog).findByText('Rechnung Oktober')).toBeTruthy();
		cleanup();
		goTo(
			'/ui/admin/master-data?tab=identifiers',
			{},
			{
				identifier: { kind: 'customer_number', ref: 'gone' }
			}
		);
		render(IdentifiersPanel);
		await vi.waitFor(() => expect(testPage.state.identifier).toBeUndefined());
	});

	it('narrows to the learned ones', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await rows();
		await user.click(screen.getByRole('button', { name: new RegExp(`^${m.open_learned()}`) }));
		await vi.waitFor(async () => expect(await rows()).toHaveLength(1));
	});

	it('shows a suggestion for a profile and takes it over there', async () => {
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await rows();
		await user.click(screen.getByRole('button', { name: new RegExp(`^${m.open_suggestions()}`) }));
		await vi.waitFor(() => expect(screen.getByText(m.open_column_target())).toBeTruthy());
		const [row] = await rows();
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

	it('names the action of a suggestion by its verb alone on a phone', async () => {
		phone.override(true);
		const user = userEvent.setup();
		render(IdentifiersPanel);
		await user.click(
			await screen.findByRole('button', { name: new RegExp(`^${m.open_suggestions()}`) })
		);
		await user.click(
			await screen.findByRole('button', { name: m.open_open({ value: SUGGESTION.written }) })
		);
		const dialog = await screen.findByRole('dialog');
		// The text names whose profile takes it.
		expect(
			within(dialog).getByText(m.open_suggested_person({ person: 'Max Nord', count: '6' }))
		).toBeTruthy();
		expect(within(dialog).getByRole('button', { name: m.open_confirm() })).toBeTruthy();
		expect(
			within(dialog).queryByRole('button', {
				name: m.open_confirm_profile({ person: 'Max Nord' })
			})
		).toBeNull();
	});
});
