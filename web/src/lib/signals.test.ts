import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { signalSummary } from '#lib/signals.ts';

type LogEntry = components['schemas']['LogEntry'];

const UTILITY = '0199a6c4-0000-7000-8000-0000000000c1';
const INVOICE = '0199a6c4-0000-7000-8000-0000000000e1';
const lookup = {
	contacts: [{ id: UTILITY, name: 'Stadtwerke' }],
	documentTypes: [{ id: INVOICE, name: 'Rechnung' }],
	tags: [],
	spaces: [],
	users: []
} as unknown as Lookup;

const entry = (node: string, output: Record<string, unknown>) =>
	({ node, output }) as unknown as LogEntry;

const texts = (rows: ReturnType<typeof signalSummary>) =>
	rows.map((row) => [row.label, row.items.map((item) => item.text)]);

describe('signalSummary', () => {
	it('tells how well the OCR read each page it recognised', () => {
		const readings = [
			{ page: 1, words: 224, unsure: 23 },
			{ page: 2, words: 400, unsure: 8 }
		];
		const rows = texts(signalSummary(entry('ocr', { readings }), lookup));
		expect(rows).toEqual([
			[
				m.log_reading(),
				[
					m.log_reading_page({ page: '1', unsure: '10%', words: '224' }),
					m.log_reading_page({ page: '2', unsure: '2%', words: '400' })
				]
			]
		]);
		expect(signalSummary(entry('ocr', { pages: 1 }), lookup)).toEqual([]);
	});

	it('adds the content words where the OCR counted them', () => {
		const readings = [{ page: 1, words: 237, unsure: 23, content: 200, content_unsure: 7 }];
		const rows = texts(signalSummary(entry('ocr', { readings }), lookup));
		expect(rows).toEqual([
			[
				m.log_reading(),
				[
					m.log_reading_page_content({
						page: '1',
						unsure: '10%',
						words: '237',
						content_unsure: '4%',
						content: '200'
					})
				]
			]
		]);
	});

	it('tells why a signal abstained', () => {
		const rows = signalSummary(entry('signal_classifier', { abstained: 'no model' }), lookup);
		expect(texts(rows)).toEqual([[m.signal_abstained(), ['no model']]]);
	});

	it('shows the language model’s proposal', () => {
		const proposal = {
			sender: { value: 'Stadtwerke GmbH', evidence: null },
			recipient: null,
			document_type: null,
			new_document_type: 'Abschlag',
			document_date: { value: '31.03.2026', evidence: null },
			title: 'Strom März',
			language: 'de'
		};
		const rows = texts(signalSummary(entry('signal_llm', { proposal }), lookup));
		expect(rows).toEqual([
			[m.signal_sender(), ['Stadtwerke GmbH']],
			[m.signal_recipient(), [m.signal_none()]],
			[m.field_document_type(), [`Abschlag (${m.candidate_new()})`]],
			[m.field_date(), ['31.03.2026']],
			[m.field_title(), ['Strom März']],
			[m.signal_language(), ['de']]
		]);
	});

	it('names the classifier’s best classes, the similar documents and the facts', () => {
		const classifier = signalSummary(
			entry('signal_classifier', {
				model: 2,
				contacts: [[UTILITY, 0.91]],
				document_types: [[INVOICE, 0.5]]
			}),
			lookup
		);
		expect(texts(classifier)).toEqual([
			[m.signal_contacts(), ['Stadtwerke 91%']],
			[m.signal_document_types(), ['Rechnung 50%']]
		]);

		const [similar] = signalSummary(
			entry('signal_neighbours', {
				neighbours: [
					{ document_id: 'd1', contact_id: UTILITY, document_type_id: null, score: 0.8776 },
					{ document_id: 'd2', contact_id: null, document_type_id: null }
				]
			}),
			lookup
		);
		expect(similar.items).toEqual([
			{
				text: `${m.signal_document({ number: 1 })}: Stadtwerke · ${m.signal_similarity({ similarity: '0.88' })}`,
				href: '/ui/documents/d1'
			},
			{ text: m.signal_document({ number: 2 }), href: '/ui/documents/d2' }
		]);

		const facts = signalSummary(
			entry('signal_facts', {
				named: [{ contact_id: UTILITY, name: 'Stadtwerke', alias: false }],
				identifiers: [{ contact_id: UTILITY, kind: 'iban', value: 'DE89' }],
				unknown_identifiers: []
			}),
			lookup
		);
		expect(texts(facts)).toEqual([
			[m.signal_named(), ['Stadtwerke']],
			[m.signal_identifiers(), [`${m.identifier_kind_iban()} DE89: Stadtwerke`]],
			[m.signal_unknown_identifiers(), [m.signal_none()]]
		]);
		expect(signalSummary(entry('judge', {}), lookup)).toEqual([]);
	});
});

describe('the topic in the signals', () => {
	const TOPIC = '0199a6c4-0000-7000-8000-0000000000b1';
	const topics = {
		...lookup,
		tags: [{ id: TOPIC, name: 'Arbeit', path: ['Arbeit'], scope: 'topic' }]
	} as unknown as Lookup;

	it('shows the topic the model named, and the classifier’s best topics', () => {
		const proposal = { sender: { value: null, evidence: null }, topic: 'Arbeit' };
		const llm = texts(signalSummary(entry('signal_llm', { proposal }), topics));
		expect(llm).toContainEqual([m.field_topic(), ['Arbeit']]);
		const output = { contacts: [], document_types: [], topics: [[TOPIC, 0.93]] };
		const classifier = texts(signalSummary(entry('signal_classifier', output), topics));
		expect(classifier).toContainEqual([m.signal_topics(), ['Arbeit 93%']]);
	});
});

describe('the labels in the fields node', () => {
	const GROSS = '0199a6c4-0000-7000-8000-0000000000f1';
	const NUMBER = '0199a6c4-0000-7000-8000-0000000000f2';
	const fields = {
		...lookup,
		fields: [
			{ id: GROSS, name: 'Bruttolohn' },
			{ id: NUMBER, name: 'Personalnummer' }
		]
	} as unknown as Lookup;
	const check = (field: string, label: unknown) => ({ field: `field:${field}`, label });

	it('tells for each value whether it stands by its label, without a link', () => {
		const output = {
			fields: [
				check(GROSS, { text: 'Gesamtbrutto', outcome: 'beside' }),
				check(NUMBER, { text: 'Pers.-Nr.', outcome: 'unknown' }),
				{ field: 'title', label: null }
			]
		};
		const rows = signalSummary(entry('fields', output), fields);
		expect(texts(rows)).toEqual([
			['Bruttolohn', [m.log_label_beside({ label: 'Gesamtbrutto' })]],
			['Personalnummer', [m.log_label_unknown({ label: 'Pers.-Nr.' })]]
		]);
		expect(rows.flatMap((row) => row.items).every((item) => item.href === undefined)).toBe(true);
	});

	it('names each outcome, and a label the model did not give', () => {
		const said = (label: unknown) =>
			texts(signalSummary(entry('fields', { fields: [check(GROSS, label)] }), fields))[0][1];
		expect(said({ text: 'Gesamtbrutto', outcome: 'apart' })).toEqual([
			m.log_label_apart({ label: 'Gesamtbrutto' })
		]);
		expect(said({ text: 'Brutto', outcome: 'label_missing' })).toEqual([
			m.log_label_missing({ label: 'Brutto' })
		]);
		expect(said({ text: null, outcome: 'no_label' })).toEqual([m.log_label_none()]);
		expect(m.log_label_beside({ label: 'Gesamtbrutto' })).toContain('Gesamtbrutto');
	});

	it('shows nothing for checks from before labels, nor for another node', () => {
		const output = { fields: [{ field: `field:${GROSS}` }] };
		expect(signalSummary(entry('fields', output), fields)).toEqual([]);
		expect(signalSummary(entry('fields', {}), fields)).toEqual([]);
		expect(signalSummary(entry('judge', output), fields)).toEqual([]);
	});
});

describe('the space in the signals and the rules', () => {
	beforeEach(() =>
		session.start({
			user: { id: '0199a6c4-0000-7000-8000-000000000001', username: 'tobi', role: 'user' },
			method: 'password',
			expires_at: '2026-10-22T12:00:00Z',
			csrf_token: 'token'
		} as never)
	);
	afterEach(() => session.clear());

	const ME = '0199a6c4-0000-7000-8000-000000000001';
	const ANNA = '0199a6c4-0000-7000-8000-000000000002';
	const MINE = '0199a6c4-0000-7000-8000-0000000000d1';
	const HOUSE = '0199a6c4-0000-7000-8000-0000000000d2';
	const ANNAS = '0199a6c4-0000-7000-8000-0000000000d3';
	const spaces = {
		...lookup,
		spaces: [
			{ id: MINE, name: 'Personal', personal_of: ME, role: 'edit', members: [] },
			{ id: HOUSE, name: 'Haushalt', personal_of: null, role: 'edit', members: [] }
		],
		users: [
			{ id: ME, username: 'tobi', role: 'user', personal_space_id: MINE },
			{ id: ANNA, username: 'anna', role: 'user', personal_space_id: ANNAS }
		]
	} as unknown as Lookup;
	const withInput = (node: string, input: Record<string, unknown>, output = {}) =>
		({ node, input, output }) as unknown as LogEntry;

	it('names the spaces of the model, the classifier and the similar documents', () => {
		const llm = texts(signalSummary(entry('signal_llm', { proposal: { space: HOUSE } }), spaces));
		expect(llm).toContainEqual([m.field_space(), ['Haushalt']]);
		const output = { contacts: [], document_types: [], spaces: [[ANNAS, 0.7]] };
		const classifier = texts(signalSummary(entry('signal_classifier', output), spaces));
		// Anna's personal space, which the caller is no member of, by her name.
		expect(classifier).toContainEqual([m.signal_spaces(), ['anna 70%']]);
		const [similar] = signalSummary(
			entry('signal_neighbours', {
				neighbours: [{ document_id: 'd1', contact_id: UTILITY, space_id: HOUSE }]
			}),
			spaces
		);
		expect(similar.items[0].text).toBe(`${m.signal_document({ number: 1 })}: Stadtwerke, Haushalt`);
	});

	it('shows the spaces a document went through, and the rules of a space it arrived in', () => {
		const chain = signalSummary(
			withInput('apply_rules', { trigger: 'ingest' }, { spaces: [MINE, HOUSE] }),
			spaces
		);
		expect(texts(chain)).toEqual([[m.log_rules_chain(), [`${m.space_personal()} → Haushalt`]]]);
		const arrived = signalSummary(
			withInput(
				'apply_rules',
				{ trigger: 'ingest', space_id: HOUSE },
				{ problem: 'rules move it back and forth: Haushalt → Persönlich → Haushalt' }
			),
			spaces
		);
		expect(texts(arrived)).toEqual([
			[m.log_rules_arrived(), ['Haushalt']],
			[m.log_rules_problem(), ['rules move it back and forth: Haushalt → Persönlich → Haushalt']]
		]);
		expect(signalSummary(withInput('apply_rules', { trigger: 'change' }), spaces)).toEqual([]);
	});

	it('names the persons the facts found and the judge weighed, and who would not see it', () => {
		const facts = signalSummary(
			entry('signal_facts', { persons: [{ user_id: ANNA, strength: 'hard' }] }),
			spaces
		);
		expect(texts(facts).at(-1)).toEqual([
			m.facts_persons(),
			[m.signal_person_hard({ name: 'anna' })]
		]);
		const judged = signalSummary(
			entry('judge', {
				fields: [{ field: 'space', outcome: 'ok', unseen_by: [ANNA, 'someone'] }],
				persons: [{ user_id: ANNA, strength: 'medium' }]
			}),
			spaces
		);
		expect(texts(judged)).toEqual([
			[m.facts_persons(), [m.signal_person_medium({ name: 'anna' })]],
			[m.log_space_unseen(), ['anna', m.space_named_someone()]]
		]);
		// Without a space check the judge's entry has nothing of its own to show.
		expect(signalSummary(entry('judge', { fields: [{ field: 'contact' }] }), spaces)).toEqual([]);
	});
});
