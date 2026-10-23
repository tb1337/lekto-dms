import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import {
	classifierRanks,
	classifierThresholds,
	drawsDetails,
	drawsFacts,
	factsOf,
	neighbourList,
	ocrNotes,
	pageBars,
	pageCharacters
} from '#lib/step-details.ts';

type LogEntry = components['schemas']['LogEntry'];

const BAKERY = '0199a6c4-0000-7000-8000-0000000000c1';
const JUKO = '0199a6c4-0000-7000-8000-0000000000c2';
const PAYSLIP = '0199a6c4-0000-7000-8000-0000000000e1';
const ANNA = '0199a6c4-0000-7000-8000-0000000000a1';
const lookup = {
	contacts: [
		{ id: BAKERY, name: 'Schwälmer Brotladen' },
		{ id: JUKO, name: 'JUKO Marburg e.V.' }
	],
	documentTypes: [{ id: PAYSLIP, name: 'Lohnabrechnung' }],
	tags: [],
	spaces: [],
	users: [{ id: ANNA, username: 'anna', display_name: 'Anna Leider' }]
} as unknown as Lookup;

const entry = (node: string, output: Record<string, unknown>) =>
	({ node, output }) as unknown as LogEntry;

describe('step details', () => {
	it('draws the steps a picture tells better, not a signal that abstained', () => {
		expect(drawsDetails(entry('ocr', {}))).toBe(true);
		expect(drawsDetails(entry('signal_classifier', { contacts: [] }))).toBe(true);
		expect(drawsDetails(entry('signal_classifier', { abstained: 'no model is trained yet' }))).toBe(
			false
		);
		expect(drawsDetails(entry('signal_llm', {}))).toBe(false);
		expect(drawsDetails(entry('signal_facts', {}))).toBe(false);
		expect(drawsFacts(entry('signal_facts', {}))).toBe(true);
		expect(drawsFacts(entry('signal_facts', { abstained: 'no text' }))).toBe(false);
	});

	it('tells how well each page was read, with the log line of the page', () => {
		const bars = pageBars({
			readings: [
				{ page: 1, words: 200, unsure: 10 },
				{ page: 2, words: 400, unsure: 72, content: 300, content_unsure: 60 }
			]
		});
		expect(bars.map((bar) => [bar.page, bar.words, bar.label])).toEqual([
			[1, 200, '5%'],
			[2, 400, '18%']
		]);
		expect(bars[1].text).toBe(
			m.log_reading_page_content({
				page: '2',
				unsure: '18%',
				words: '400',
				content_unsure: '20%',
				content: '300'
			})
		);
	});

	it('notes what the text recognition did beside reading', () => {
		expect(ocrNotes({ pdfa: true })).toEqual([]);
		expect(
			ocrNotes({ pdfa: false, rgb: true, read_again: true, vision: { model: 'qwen-vl', calls: 3 } })
		).toEqual([
			m.details_not_pdfa(),
			m.details_rgb(),
			m.details_read_again(),
			m.details_vision({ model: 'qwen-vl', calls: '3' })
		]);
	});

	it('counts the characters of each page of the text', () => {
		expect(pageCharacters('first page\n\f\nsecond\n\f\nthird')).toEqual([10, 6, 5]);
		expect(pageCharacters('one page only')).toEqual([13]);
	});

	it("takes the classifier's threshold from the verdict and draws its classes against it", () => {
		const verdict = entry('judge', {
			fields: [
				{
					field: 'contact',
					candidates: [
						{ sources: [{ signal: 'signal_llm', names: true }] },
						{ sources: [{ signal: 'signal_classifier', score: 0.52, threshold: 0.8 }] }
					]
				},
				{ field: 'date', candidates: [] }
			]
		});
		const thresholds = classifierThresholds(verdict);
		expect(thresholds).toEqual({ contacts: 0.8 });
		expect(classifierThresholds(undefined)).toEqual({});
		const groups = classifierRanks(
			{
				contacts: [
					[JUKO, 0.52],
					[BAKERY, 0.31]
				],
				document_types: [[PAYSLIP, 0.91]],
				topics: []
			},
			lookup,
			thresholds
		);
		expect(groups.map((group) => [group.kind, group.threshold])).toEqual([
			['contacts', 0.8],
			['document_types', null],
			['topics', null]
		]);
		expect(groups[0].ranks).toEqual([
			{ name: 'JUKO Marburg e.V.', share: 0.52, label: '52%' },
			{ name: 'Schwälmer Brotladen', share: 0.31, label: '31%' }
		]);
	});

	it('lists the similar documents with what they carry and how similar they are', () => {
		const neighbours = neighbourList(
			{
				neighbours: [
					{ document_id: 'd-1', score: 0.912, contact_id: JUKO, document_type_id: PAYSLIP },
					{ document_id: 'd-2' }
				]
			},
			lookup
		);
		expect(neighbours[0]).toEqual({
			title: m.signal_document({ number: 1 }),
			href: '/ui/documents/d-1',
			about: 'JUKO Marburg e.V. · Lohnabrechnung',
			similarity: 0.912,
			label: '0.91'
		});
		expect(neighbours[1].similarity).toBeNull();
	});

	it('tells what the text names: contacts, identifiers with their contact, persons in brackets', () => {
		const facts = factsOf(
			{
				named: [{ name: 'Schwälmer Brotladen' }, { name: 'N26' }],
				identifiers: [{ kind: 'personnel_number', value: '20417', contact_id: BAKERY }],
				unknown_identifiers: [{ kind: 'iban', value: 'DE89 3704 0044 0532 0130 00' }],
				persons: [{ user_id: ANNA, strength: 'weak' }]
			},
			lookup
		);
		expect(facts.named).toEqual(['Schwälmer Brotladen', 'N26']);
		expect(facts.identifiers).toHaveLength(1);
		expect(facts.identifiers[0]).toMatch(/20417 → Schwälmer Brotladen$/);
		expect(facts.unknown[0]).toMatch(/DE89 3704 0044 0532 0130 00$/);
		expect(facts.persons).toEqual([m.signal_person_weak({ name: 'Anna Leider' })]);
	});
});
