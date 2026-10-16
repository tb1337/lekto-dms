import { fireEvent, render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Mark, Review } from '#lib/document-view.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import DocumentForm from './DocumentForm.svelte';

type Document = components['schemas']['DocumentDetails'];

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const OWNER = '0199a6c4-0000-7000-8000-000000000001';
const DRAWER = '0199a6c4-0000-7000-8000-0000000000d1';
const CONTACT = '0199a6c4-0000-7000-8000-0000000000c1';
const BANK = '0199a6c4-0000-7000-8000-0000000000c2';
const SIMILAR = '0199a6c4-0000-7000-8000-0000000000a1';
const INVOICE = '0199a6c4-0000-7000-8000-0000000000e1';
const NUMBER = '0199a6c4-0000-7000-8000-0000000000f1';
const NOTE = '0199a6c4-0000-7000-8000-0000000000f2';

const named = (id: string, name: string) => ({ id, name }) as Lookup['contacts'][number];

const lookup = {
	contacts: [named(CONTACT, 'Stadtwerke Musterstadt'), named(BANK, 'Beispielbank')],
	documentTypes: [named(INVOICE, 'Rechnung')],
	tags: [],
	fields: [
		{
			id: NUMBER,
			name: 'Rechnungsnummer',
			data_type: 'text',
			document_type_ids: [INVOICE],
			required: false,
			required_document_type_ids: [INVOICE],
			choices: [],
			description: 'Die Nummer, unter der die Rechnung geführt wird'
		},
		{
			id: NOTE,
			name: 'Notiz',
			data_type: 'text',
			document_type_ids: null,
			required: false,
			required_document_type_ids: [],
			choices: []
		}
	],
	drawers: [{ id: DRAWER, name: 'Haushalt', owner_id: OWNER, access: 'read_write' }],
	users: []
} as unknown as Lookup;

function documentOf(status: string, lane: string | null = 'yellow'): Document {
	return {
		lane,
		id: 'doc-1',
		title: 'Stromrechnung März 2026',
		owner_id: OWNER,
		drawer_id: DRAWER,
		access: 'read_write',
		contact_id: null,
		document_type_id: INVOICE,
		tag_ids: [],
		document_date: '2026-03-12',
		fields: { [NUMBER]: 'R-2026-03-1182' },
		processing: { status, run: 1, nodes: [] }
	} as unknown as Document;
}

const place = { page: 1, boxes: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.02 }] };

function check(field: string, changes: Record<string, unknown> = {}) {
	return {
		field,
		outcome: 'ok',
		confidence: 1,
		reason: null,
		proposed: null,
		evidence: null,
		value: null,
		suggestion: null,
		new_name: null,
		quote_shows_value: null,
		locations: [],
		candidates: [],
		...changes
	};
}

const review = {
	document: {},
	open: [
		{
			node: 'judge',
			outcome: 'uncertain',
			reason: 'contact',
			fields: [
				check('contact', {
					outcome: 'uncertain',
					confidence: 0.62,
					reason: 'Name nur ähnlich',
					proposed: 'Stadtwerke Musterstadt GmbH',
					evidence: 'Stadtwerke Musterstadt GmbH',
					suggestion: CONTACT,
					quote_shows_value: true,
					locations: [place]
				})
			]
		}
	],
	nodes: [
		{
			node: 'judge',
			run: 1,
			outcome: 'uncertain',
			reason: 'contact',
			model_version: 'qwen3:8b',
			truncated: false,
			fields: [
				check('document_date', {
					evidence: 'Rechnungsdatum 12.03.2026',
					value: '2026-03-12',
					quote_shows_value: true,
					locations: [place]
				})
			]
		}
	]
} as unknown as Review;

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

function props(overrides: Record<string, unknown> = {}) {
	return {
		document: documentOf('review'),
		lookup,
		review,
		editable: true,
		next: 'doc-2',
		onsaved: vi.fn(),
		onconfirmed: vi.fn(),
		onmarks: vi.fn<(marks: Mark[]) => void>(),
		onreveal: vi.fn(),
		...overrides
	};
}

beforeEach(() => {
	session.start({
		user: { id: OWNER, username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-09T12:00:00Z',
		csrf_token: 'token'
	});
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

describe('DocumentForm', () => {
	it('groups the fields: basics, global ones and those of the type', () => {
		render(DocumentForm, props());
		expect(screen.getByRole('heading', { name: m.group_basics() })).toBeTruthy();
		expect(screen.getByRole('heading', { name: m.group_global() })).toBeTruthy();
		expect(screen.getByRole('heading', { name: m.group_type({ type: 'Rechnung' }) })).toBeTruthy();
		const global = screen.getByRole('region', { name: m.group_global() });
		expect(within(global).getByLabelText('Notiz', { selector: 'input' })).toBeTruthy();
	});

	it('links from the contact to the facts of the document, when there are any', () => {
		const counts = { evidence: 2, unknown: 0, codes: 1 };
		render(DocumentForm, props({ factCounts: counts, factsHref: '/documents/d/content' }));
		const card = screen.getByRole('group', { name: m.field_contact() });
		// Counted in singular and plural; what there is none of is left out.
		const chip = within(card).getByRole('link', {
			name: `${m.facts_chip_evidence({ count: 2 })} · ${m.facts_chip_codes_one()}`
		});
		expect(chip.getAttribute('href')).toBe('/documents/d/content');
	});

	it('shows no link to the facts without them', () => {
		render(DocumentForm, props({ factCounts: { evidence: 0, unknown: 0, codes: 0 } }));
		expect(screen.queryByRole('link', { name: /Belege|evidence/ })).toBeNull();
	});

	it('shows each page of a quote once, and many behind +N', async () => {
		const pages = [1, 5, 7, 9, 9, 13, 14, 17, 18].map((page) => ({ ...place, page }));
		const many = structuredClone(review) as unknown as {
			open: { fields: { locations: unknown }[] }[];
		};
		many.open[0].fields[0].locations = pages;
		render(DocumentForm, props({ review: many as unknown as Review }));
		const card = screen.getByRole('group', { name: m.field_contact() });
		const chips = () => within(card).getAllByRole('button', { name: /Seite \d+$|page \d+$/ });
		// Eight pages (9 twice): six chips, two behind +2.
		expect(chips()).toHaveLength(6);
		await userEvent.click(within(card).getByRole('button', { name: m.source_more({ count: 2 }) }));
		expect(chips()).toHaveLength(8);
		expect(within(card).getByText('Stadtwerke Musterstadt GmbH', { selector: 'q' })).toBeTruthy();
	});

	it('tells under a field what belongs in it', () => {
		render(DocumentForm, props());
		const number = screen.getByRole('group', { name: /Rechnungsnummer/ });
		expect(number.getAttribute('aria-describedby')).toBeTruthy();
		expect(
			within(number).getByText('Die Nummer, unter der die Rechnung geführt wird')
		).toBeTruthy();
		const note = screen.getByRole('group', { name: 'Notiz' });
		expect(note.getAttribute('aria-describedby')).toBeNull();
	});

	it('shows an open field as a card with reason and quote', () => {
		render(DocumentForm, props());
		const card = screen.getByRole('group', { name: m.field_contact() });
		expect(within(card).getByText('Name nur ähnlich')).toBeTruthy();
		expect(within(card).getByText(m.review_evidence())).toBeTruthy();
		expect(within(card).getByText('Stadtwerke Musterstadt GmbH')).toBeTruthy();
		// The suggestion is preselected.
		const select = screen.getByLabelText(m.field_contact(), { selector: 'select' });
		expect((select as HTMLSelectElement).value).toBe(CONTACT);
	});

	it('lists what the signals propose; a click takes one, a contradiction is marked', async () => {
		const proposals = {
			document: {},
			open: [
				{
					node: 'judge',
					outcome: 'uncertain',
					reason: 'contact',
					fields: [
						check('contact', {
							outcome: 'uncertain',
							confidence: 0.82,
							reason: 'the signals disagree',
							suggestion: CONTACT,
							candidates: [
								{
									value: CONTACT,
									label: 'Stadtwerke Musterstadt',
									contradicted: true,
									sources: [
										{ signal: 'signal_llm', names: false, score: 0.82, quote: 'Stadtwerk' },
										{ signal: 'signal_facts', names: false, named_in_text: true }
									]
								},
								{
									value: BANK,
									label: 'Beispielbank',
									contradicted: true,
									sources: [
										{
											signal: 'signal_neighbours',
											names: true,
											votes: 2,
											found: 3,
											documents: [SIMILAR]
										}
									]
								},
								{
									value: null,
									label: 'Stadtwerk Netz',
									contradicted: false,
									sources: [{ signal: 'signal_llm', names: false }]
								}
							]
						})
					]
				}
			],
			nodes: []
		} as unknown as Review;
		render(DocumentForm, props({ review: proposals }));
		const card = screen.getByRole('group', { name: m.field_contact() });
		expect(within(card).getByText(m.candidates_title())).toBeTruthy();
		expect(within(card).getAllByText(m.candidate_contradicted())).toHaveLength(2);
		expect(within(card).getByText(m.candidate_named())).toBeTruthy();
		// The model's quote is read out, not only shown on hover.
		expect(within(card).getByText(': „Stadtwerk“')).toBeTruthy();
		expect(within(card).getByText(m.candidate_new())).toBeTruthy();
		expect(within(card).getByText(m.candidate_neighbours({ votes: 2, found: 3 }))).toBeTruthy();
		const similar = within(card).getByRole('link', { name: m.candidate_document({ number: 1 }) });
		expect(similar.getAttribute('href')).toBe(`/ui/documents/${SIMILAR}`);

		const select = screen.getByLabelText(m.field_contact(), { selector: 'select' });
		expect((select as HTMLSelectElement).value).toBe(CONTACT);
		await userEvent.click(
			within(card).getByRole('button', { name: m.candidate_pick({ name: 'Beispielbank' }) })
		);
		expect((select as HTMLSelectElement).value).toBe(BANK);
	});

	it('tells where a green value comes from, and marks required fields', async () => {
		const green = {
			document: {},
			open: [],
			nodes: [
				{
					node: 'judge',
					run: 1,
					outcome: 'ok',
					reason: null,
					model_version: 'qwen3:8b',
					truncated: false,
					fields: [
						check('document_type', {
							value: INVOICE,
							candidates: [
								{
									value: INVOICE,
									label: 'Rechnung',
									contradicted: false,
									sources: [
										{ signal: 'signal_llm', names: true },
										{ signal: 'signal_classifier', names: true, score: 0.94 }
									]
								}
							]
						})
					]
				}
			]
		} as unknown as Review;
		render(
			DocumentForm,
			props({ document: documentOf('completed', 'green'), review: green, next: null })
		);
		const kind = screen.getByRole('group', { name: m.field_document_type() });
		await userEvent.click(within(kind).getByRole('button', { name: m.sources_details() }));
		expect(within(kind).getByText(m.candidate_classifier({ score: '94%' }))).toBeTruthy();
		expect(within(kind).getByText(m.candidate_llm())).toBeTruthy();

		const number = screen.getByRole('group', { name: /Rechnungsnummer/ });
		expect(within(number).getByText(`(${m.field_required()})`)).toBeTruthy();
		const note = screen.getByRole('group', { name: 'Notiz' });
		expect(within(note).queryByText(`(${m.field_required()})`)).toBeNull();
	});

	it('marks the quote of the field under the pointer, while the value is the checked one', async () => {
		const onmarks = vi.fn<(marks: Mark[]) => void>();
		render(DocumentForm, props({ onmarks }));
		const dated = screen.getByRole('group', { name: m.field_date() });
		await fireEvent.mouseEnter(dated);
		await tick();
		expect(onmarks).toHaveBeenLastCalledWith([
			{ key: 'document_date', label: m.field_date(), ...place, derived: false, pinned: false }
		]);
		const input = screen.getByLabelText(m.field_date(), { selector: 'input' });
		await fireEvent.input(input, { target: { value: '2026-04-01' } });
		await tick();
		expect(onmarks).toHaveBeenLastCalledWith([]);
	});

	it('jumps to a source from its page', async () => {
		const onreveal = vi.fn();
		render(DocumentForm, props({ onreveal }));
		const card = screen.getByRole('group', { name: m.field_contact() });
		await userEvent.click(within(card).getByRole('button', { name: m.source_jump({ page: 1 }) }));
		expect(onreveal).toHaveBeenCalledWith(place);
	});

	it('confirms every open field at once and goes on to the next document', async () => {
		fetchMock.mockResolvedValue(
			new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
		);
		const onconfirmed = vi.fn();
		render(DocumentForm, props({ onconfirmed }));
		await userEvent.click(screen.getByRole('button', { name: m.review_confirm() }));
		const request = fetchMock.mock.calls[0][0];
		expect(new URL(request.url).pathname).toBe('/api/v1/documents/doc-1/confirm');
		expect(await request.json()).toEqual({
			changes: { contact_id: CONTACT },
			accept_suggestions: false,
			resume_at: 'apply_rules'
		});
		expect(onconfirmed).toHaveBeenCalledWith('doc-2');
	});

	it('outside the inbox, shows a change as a dry run first', async () => {
		render(
			DocumentForm,
			props({ document: documentOf('completed', 'green'), review: null, next: null })
		);
		const button = screen.getByRole('button', { name: m.edit_review() });
		expect((button as HTMLButtonElement).disabled).toBe(true);
		expect(screen.queryByRole('button', { name: m.review_confirm() })).toBeNull();
		await userEvent.type(screen.getByLabelText('Notiz', { selector: 'input' }), 'bezahlt');
		expect((button as HTMLButtonElement).disabled).toBe(false);
	});

	it('confirms a filed document that waits for its drawer, with the drawer to file into', async () => {
		fetchMock.mockResolvedValue(
			new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
		);
		const waiting = {
			document: {},
			open: [
				{
					node: 'file',
					outcome: 'uncertain',
					reason: 'drawer',
					fields: [check('drawer', { outcome: 'uncertain', reason: 'no write access' })]
				}
			],
			nodes: []
		} as unknown as Review;
		render(DocumentForm, props({ document: documentOf('completed'), review: waiting, next: null }));
		expect(screen.getByLabelText(m.field_drawer(), { selector: 'select' })).toBeTruthy();
		await userEvent.click(screen.getByRole('button', { name: m.review_confirm() }));
		expect(await fetchMock.mock.calls[0][0].json()).toEqual({
			changes: {},
			accept_suggestions: false,
			resume_at: 'apply_rules'
		});
	});

	it('lets a failed document with nothing to decide be changed instead of confirmed', () => {
		const failed = {
			document: {},
			open: [{ node: 'ocr', outcome: 'failed', reason: 'the PDF is damaged', fields: [] }],
			nodes: []
		} as unknown as Review;
		render(DocumentForm, props({ document: documentOf('failed', 'red'), review: failed }));
		expect(screen.getByText('the PDF is damaged')).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.review_confirm() })).toBeNull();
		expect(screen.getByRole('button', { name: m.edit_review() })).toBeTruthy();
	});

	it("after a corrected type sends no suggestion of the old type as the owner's value", async () => {
		fetchMock.mockResolvedValue(
			new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
		);
		const OTHER = '0199a6c4-0000-7000-8000-0000000000e2';
		const typed = {
			document: {},
			open: [
				{
					node: 'fields',
					outcome: 'uncertain',
					reason: 'note',
					fields: [
						check(`field:${NOTE}`, { outcome: 'uncertain', reason: 'x', suggestion: 'bezahlt' })
					]
				}
			],
			nodes: []
		} as unknown as Review;
		const withOther = {
			...lookup,
			documentTypes: [...lookup.documentTypes, named(OTHER, 'Vertrag')]
		};
		render(DocumentForm, props({ review: typed, lookup: withOther, next: null }));
		await userEvent.selectOptions(
			screen.getByLabelText(m.field_document_type(), { selector: 'select' }),
			OTHER
		);
		await userEvent.click(screen.getByRole('button', { name: m.review_confirm() }));
		expect(await fetchMock.mock.calls[0][0].json()).toEqual({
			changes: { document_type_id: OTHER },
			accept_suggestions: false,
			resume_at: 'fields'
		});
	});
});
