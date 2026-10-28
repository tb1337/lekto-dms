import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Facts } from '#lib/facts.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { choose } from '#lib/testing/select.ts';
import FactsPanel from './FactsPanel.svelte';

const UTILITY = 'contact-1';
const BANK = 'contact-2';
const FIELD = 'field-1';

const lookup = {
	contacts: [
		{ id: UTILITY, name: 'Stadtwerke Musterstadt GmbH' },
		{ id: BANK, name: 'Bank Musterstadt' }
	],
	documentTypes: [],
	tags: [],
	fields: [{ id: FIELD, name: 'Rechnungsbetrag' }],
	spaces: [],
	users: []
} as unknown as Lookup;

const FACTS: Facts = {
	contact_id: UTILITY,
	editable: false,
	named: [
		{
			contact_id: UTILITY,
			name: 'Stadtwerke Musterstadt GmbH',
			alias: false,
			in_text: true,
			in_code: false,
			spans: [{ start: 0, end: 22, locations: [] }]
		}
	],
	identifiers: [
		{
			kind: 'iban',
			value: 'DE89370400440532013000',
			contact_id: UTILITY,
			in_text: true,
			in_code: true,
			role: 'contact',
			origins: ['pattern', 'code'],
			state: 'found',
			kept: true,
			spans: [{ start: 40, end: 67, locations: [] }],
			other_contacts: 0
		},
		{
			kind: 'customer_number',
			value: '20047718',
			contact_id: null,
			in_text: true,
			in_code: false,
			role: 'contact',
			origins: ['pattern'],
			state: 'found',
			kept: true,
			spans: [{ start: 80, end: 89, locations: [] }],
			other_contacts: 0
		},
		{
			kind: 'iban',
			value: 'DE02120300000000202051',
			contact_id: null,
			in_text: true,
			in_code: false,
			role: 'contact',
			origins: ['pattern'],
			state: 'found',
			kept: true,
			spans: [{ start: 100, end: 127, locations: [] }],
			other_contacts: 6
		}
	],
	codes: [
		{
			format: 'QR Code',
			text: 'BCD\n002',
			places: [{ page: 1, boxes: [{ x: 0.7, y: 0.8, width: 0.1, height: 0.1 }] }],
			giro: {
				name: 'Stadtwerke Musterstadt GmbH',
				iban: 'DE89370400440532013000',
				bic: 'MUSTDEM1XXX',
				amount: { amount: '84.20', currency: 'EUR' },
				purpose: 'Abschlag 03/2026'
			},
			identifiers: [{ kind: 'iban', value: 'DE89370400440532013000' }],
			fields: [FIELD]
		},
		{
			format: 'Data Matrix',
			text: 'DEA5E12C0001',
			// The same code on two pages: one entry.
			places: [
				{ page: 2, boxes: [{ x: 0.8, y: 0.05, width: 0.1, height: 0.05 }] },
				{ page: 4, boxes: [{ x: 0.8, y: 0.05, width: 0.1, height: 0.05 }] }
			],
			giro: null,
			identifiers: [],
			fields: []
		}
	]
};

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

function props(overrides: Record<string, unknown> = {}) {
	return {
		facts: FACTS,
		documentId: 'doc-1',
		lookup,
		admin: true,
		onmark: vi.fn(),
		onshowcode: vi.fn(),
		onchanged: vi.fn(),
		...overrides
	};
}

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () => new Response('{}', { status: 200 }));
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('FactsPanel', () => {
	it('shows what supports the contact, what has no contact, and the codes', () => {
		render(FactsPanel, props());
		const own = screen.getByRole('heading', { name: /Stadtwerke Musterstadt GmbH/ });
		expect(own.textContent).toContain(m.facts_own());
		// The IBAN as a fact, and as the GiroCode's.
		expect(screen.getAllByText('DE89 3704 0044 0532 0130 00')).toHaveLength(2);
		expect(screen.getByText(m.facts_unknown())).toBeTruthy();
		expect(screen.getByText('20047718')).toBeTruthy();
		// Each with what it is to the document.
		expect(screen.getAllByText(`· ${m.fact_role_contact()}`)).toHaveLength(3);
		// The owner's own IBAN stands on many contacts' documents.
		expect(screen.getByText(m.facts_other_contacts({ count: 6 }))).toBeTruthy();
		// Only a pin to attach, its label on hover.
		expect(screen.getAllByRole('button', { name: /^Pin .* as an identifier$/ })).toHaveLength(2);
		// The GiroCode read, its amount as the field's; another code as it is.
		expect(screen.getByText(m.code_giro())).toBeTruthy();
		expect(screen.getByText(m.code_same_as({ field: 'Rechnungsbetrag' }))).toBeTruthy();
		expect(screen.getByText('DEA5E12C0001')).toBeTruthy();
	});

	it('marks a fact while hovered, and keeps it on a click', async () => {
		const onmark = vi.fn();
		render(FactsPanel, props({ onmark }));
		const customer = screen.getByRole('button', {
			name: new RegExp(`^${m.identifier_kind_customer_number()}`)
		});
		await fireEvent.mouseEnter(customer.parentElement!.parentElement!);
		const spans = [{ start: 80, end: 89, locations: [] }];
		// On the pages under its kind.
		const kind = m.identifier_kind_customer_number();
		expect(onmark).toHaveBeenLastCalledWith(spans, false, kind);
		await fireEvent.click(customer);
		expect(onmark).toHaveBeenLastCalledWith(spans, true, kind);
		expect(customer.getAttribute('aria-pressed')).toBe('true');
	});

	it('lists the document’s numbers with their roles and marks them', async () => {
		const onmark = vi.fn();
		const spans = [{ start: 30, end: 34, locations: [] }];
		const numbers = [
			{
				kind: 'invoice_number',
				value: '4711',
				written: '4711',
				role: 'refers',
				origins: ['pattern'],
				state: 'found',
				spans
			}
		];
		render(FactsPanel, props({ onmark, facts: { ...FACTS, numbers } }));
		expect(screen.getByRole('heading', { name: m.facts_numbers() })).toBeTruthy();
		const row = screen.getByRole('button', {
			name: new RegExp(`^${m.identifier_kind_invoice_number()}`)
		});
		expect(row.textContent).toContain(m.fact_role_refers());
		await fireEvent.mouseEnter(row.closest('[role="presentation"]')!);
		expect(onmark).toHaveBeenLastCalledWith(spans, false, m.identifier_kind_invoice_number());
	});

	it('marks what of a code stands in the text, and shows a code on each of its pages', async () => {
		const onmark = vi.fn();
		const onshowcode = vi.fn();
		render(FactsPanel, props({ onmark, onshowcode }));
		await fireEvent.click(
			screen.getByRole('button', { name: m.codes_mark({ format: 'QR Code' }) })
		);
		expect(onmark).toHaveBeenLastCalledWith(
			[{ start: 40, end: 67, locations: [] }],
			true,
			'QR Code'
		);
		await fireEvent.click(screen.getByRole('button', { name: m.source_jump({ page: 1 }) }));
		expect(onshowcode).toHaveBeenLastCalledWith(FACTS.codes![0], FACTS.codes![0].places[0]);
		const matrix = FACTS.codes![1];
		expect(screen.getAllByRole('button', { name: m.source_jump({ page: 2 }) })).toHaveLength(1);
		await fireEvent.click(screen.getByRole('button', { name: m.source_jump({ page: 4 }) }));
		expect(onshowcode).toHaveBeenLastCalledWith(matrix, matrix.places[1]);
	});

	it('lets an admin attach an identifier to the document contact', async () => {
		const onchanged = vi.fn();
		render(FactsPanel, props({ onchanged }));
		const user = userEvent.setup();
		await user.click(screen.getAllByRole('button', { name: /^Pin .* as an identifier$/ })[0]);
		const form = screen.getByText(
			m.facts_attach_title({ kind: m.identifier_kind_customer_number() })
		).parentElement!;
		expect(
			within(form)
				.getByRole('radio', { name: /Stadtwerke Musterstadt GmbH/ })
				.getAttribute('value')
		).toBe('document');
		await user.click(within(form).getByRole('button', { name: m.facts_attach() }));
		await waitFor(() => expect(onchanged).toHaveBeenCalled());
		const [request] = fetchMock.mock.calls[0];
		expect(new URL(request.url).pathname).toBe(`/api/v1/contacts/${UTILITY}/identifiers`);
		expect(await request.json()).toEqual({ kind: 'customer_number', value: '20047718' });
	});

	it('lets an editor correct, reject and add a fact (#145)', async () => {
		const onchanged = vi.fn();
		const number = {
			kind: 'invoice_number' as const,
			value: '4711',
			written: '4711',
			role: 'own' as const,
			origins: ['pattern' as const],
			state: 'found' as const,
			spans: []
		};
		const rejected = { ...number, value: 'M77', written: 'M-77', state: 'rejected' as const };
		render(
			FactsPanel,
			props({ onchanged, facts: { ...FACTS, editable: true, numbers: [number, rejected] } })
		);
		const user = userEvent.setup();
		const body = async (index: number) => fetchMock.mock.calls[index][0].json();

		// The role of the invoice it refers to.
		await user.click(
			screen.getByRole('button', { name: m.facts_decide_value_label({ value: '4711' }) })
		);
		await choose(user, screen.getByRole('combobox', { name: m.facts_decide_role() }), 'refers');
		await user.click(screen.getByRole('button', { name: m.facts_decide_save() }));
		await waitFor(() => expect(onchanged).toHaveBeenCalledTimes(1));
		expect(await body(0)).toEqual({
			at_contact: false,
			action: 'correct',
			kind: 'invoice_number',
			value: '4711',
			role: 'refers'
		});

		// A rejected one is only restored.
		expect(screen.getByText(m.facts_state_rejected())).toBeTruthy();
		await user.click(
			screen.getByRole('button', { name: m.facts_decide_value_label({ value: 'M-77' }) })
		);
		expect(screen.queryByRole('button', { name: m.facts_decide_save() })).toBeNull();
		await user.click(screen.getByRole('button', { name: m.facts_decide_restore() }));
		await waitFor(() => expect(onchanged).toHaveBeenCalledTimes(2));
		expect((await body(1)).action).toBe('withdraw');

		// Added, with the role of its kind.
		await user.click(screen.getByRole('button', { name: m.facts_add() }));
		await user.type(screen.getByRole('textbox', { name: m.facts_decide_value() }), 'R-1001');
		await user.click(screen.getByRole('button', { name: m.facts_add_save() }));
		await waitFor(() => expect(onchanged).toHaveBeenCalledTimes(3));
		expect(await body(2)).toEqual({
			at_contact: false,
			action: 'add',
			kind: 'invoice_number',
			value: 'R-1001',
			role: 'own'
		});
	});

	it("opens the contact's dialog from its name, for admins", async () => {
		const open = vi.spyOn(masterDataDialogs, 'open').mockImplementation(() => {});
		render(FactsPanel, props());
		const own = screen.getByRole('heading', { name: /Stadtwerke Musterstadt GmbH/ });
		await fireEvent.click(within(own).getByRole('button', { name: 'Stadtwerke Musterstadt GmbH' }));
		expect(open).toHaveBeenCalledWith('contacts', UTILITY);
		open.mockRestore();
	});

	it('names the other contacts an identifier stands with, each to open, and the code’s', async () => {
		const open = vi.spyOn(masterDataDialogs, 'open').mockImplementation(() => {});
		const facts = {
			...FACTS,
			identifiers: FACTS.identifiers.map((item) =>
				item.other_contacts ? { ...item, other_contacts: 1, other_contact_ids: [BANK] } : item
			)
		};
		render(FactsPanel, props({ facts }));
		const warning = screen.getByText(m.facts_other_contacts_of()).closest('div')!;
		await fireEvent.click(within(warning).getByRole('button', { name: 'Bank Musterstadt' }));
		expect(open).toHaveBeenLastCalledWith('contacts', BANK);
		// The GiroCode's IBAN is the utility's: the code names it.
		const giro = screen.getByText(m.code_giro()).closest('div')!.parentElement!;
		expect(within(giro).getByRole('button', { name: 'Stadtwerke Musterstadt GmbH' })).toBeTruthy();
		open.mockRestore();
	});

	it('offers nothing to attach to those who are no admins', () => {
		render(FactsPanel, props({ admin: false }));
		const own = screen.getByRole('heading', { name: /Stadtwerke Musterstadt GmbH/ });
		expect(within(own).queryByRole('button')).toBeNull();
		expect(screen.queryAllByRole('button', { name: /^Pin .* as an identifier$/ })).toHaveLength(0);
		expect(screen.getByText(m.facts_attach_admins())).toBeTruthy();
	});

	it('folds the numbers of third parties away, with their holders', async () => {
		const payee = {
			...FACTS.identifiers[2],
			value: 'DE17100500000123456789',
			contact_id: BANK,
			holder: { kind: 'third_party', name: 'Hausverwaltung Ost', source: 'rule' }
		} as Facts['identifiers'][number];
		render(FactsPanel, props({ facts: { ...FACTS, identifiers: [...FACTS.identifiers, payee] } }));
		const fold = screen.getByRole('button', { name: new RegExp(m.facts_third_one()) });
		expect(fold.getAttribute('aria-expanded')).toBe('false');
		expect(screen.queryByText('DE17 1005 0000 0123 4567 89')).toBeNull();
		await userEvent.click(fold);
		expect(fold.getAttribute('aria-expanded')).toBe('true');
		expect(screen.getByText('DE17 1005 0000 0123 4567 89')).toBeTruthy();
		expect(
			screen.getByText(
				m.facts_holder_named({
					holder: m.fact_holder_third_party(),
					name: 'Hausverwaltung Ost',
					source: m.fact_holder_source_rule()
				})
			)
		).toBeTruthy();
	});

	it('names the contact an identifier is rejected at, with nothing to attach', () => {
		const rejected = {
			...FACTS.identifiers[2],
			rejected_at: BANK,
			holder: { kind: 'recipient', name: null, source: 'rule' }
		} as Facts['identifiers'][number];
		render(
			FactsPanel,
			props({ facts: { ...FACTS, identifiers: [FACTS.identifiers[0], rejected] } })
		);
		expect(screen.getByText(m.facts_rejected_at({ contact: 'Bank Musterstadt' }))).toBeTruthy();
		expect(
			screen.queryByRole('button', {
				name: m.facts_attach_value({ value: 'DE02 1203 0000 0000 2020 51' })
			})
		).toBeNull();
	});

	it('says when the codes are not read yet', () => {
		render(FactsPanel, props({ facts: { ...FACTS, codes: null } }));
		expect(screen.getByText(m.codes_unread())).toBeTruthy();
	});
});
