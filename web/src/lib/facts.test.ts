import { describe, expect, it } from 'vitest';
import {
	codeSpans,
	evidenceLabel,
	factCounts,
	grouped,
	inUnits,
	pageRanges,
	quoteStretches,
	segmentsOf,
	shown,
	spanMarks,
	strengthLabel,
	type Facts
} from './facts.ts';
import { m } from '#lib/paraglide/messages.js';

const CONTACT = 'contact-1';

const FACTS: Facts = {
	contact_id: CONTACT,
	editable: false,
	named: [
		{
			contact_id: CONTACT,
			name: 'Lekto Test GmbH',
			alias: false,
			in_text: true,
			in_code: true,
			spans: [{ start: 0, end: 10, locations: [] }]
		}
	],
	identifiers: [
		{
			kind: 'iban',
			value: 'DE89370400440532013000',
			contact_id: CONTACT,
			in_text: true,
			in_code: true,
			role: 'contact',
			origins: ['pattern', 'code'],
			state: 'found',
			spans: [{ start: 20, end: 47, locations: [] }],
			other_contacts: null
		},
		{
			kind: 'vat_id',
			value: 'DE312456789',
			contact_id: 'contact-2',
			in_text: true,
			in_code: false,
			role: 'contact',
			origins: ['pattern'],
			state: 'found',
			spans: [],
			other_contacts: null
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
			spans: [{ start: 60, end: 69, locations: [] }],
			other_contacts: 0
		}
	],
	codes: [
		{
			format: 'QR Code',
			text: 'BCD',
			places: [{ page: 1, boxes: [{ x: 0.7, y: 0.8, width: 0.1, height: 0.1 }] }],
			giro: {
				name: 'Lekto Test GmbH',
				iban: 'DE89370400440532013000',
				bic: null,
				amount: { amount: '123.45', currency: 'EUR' },
				purpose: null
			},
			identifiers: [{ kind: 'iban', value: 'DE89370400440532013000' }],
			fields: []
		}
	]
};

describe('pages and marks', () => {
	it('finds where each page starts, as the text view splits it', () => {
		const text = 'one\n\f\ntwo\fthree';
		const ranges = pageRanges(text);
		expect(ranges.map((range) => text.slice(range.start, range.end))).toEqual(
			text.split(/\n?\f\n?/)
		);
	});

	it('marks the stretches of a page within the marks', () => {
		const text = 'abcdefghij';
		expect(
			segmentsOf(text, { start: 2, end: 9 }, [
				{ start: 0, end: 4 },
				{ start: 6, end: 7 },
				{ start: 6, end: 8 }
			])
		).toEqual([
			{ text: 'cd', marked: true },
			{ text: 'ef', marked: false },
			{ text: 'g', marked: true },
			{ text: 'hi', marked: false }
		]);
		expect(segmentsOf(text, { start: 0, end: 3 }, [])).toEqual([{ text: 'abc', marked: false }]);
	});

	it('counts characters beyond the basic plane twice, as JavaScript does', () => {
		const text = 'a😀b IBAN';
		expect(inUnits('plain', [{ start: 1, end: 3 }])).toEqual([{ start: 1, end: 3 }]);
		expect(inUnits(text, [{ start: 4, end: 8 }])).toEqual([{ start: 5, end: 9 }]);
	});
});

describe('facts', () => {
	it('groups them by the document contact, others and none', () => {
		const groups = grouped(FACTS);
		expect(groups.own.map((item) => ('name' in item ? item.name : item.value))).toEqual([
			'Lekto Test GmbH',
			'DE89370400440532013000'
		]);
		expect(groups.others.map((item) => ('value' in item ? item.value : ''))).toEqual([
			'DE312456789'
		]);
		expect(groups.unknown.map((item) => item.value)).toEqual(['20047718']);
		expect(factCounts(FACTS)).toEqual({ evidence: 2, unknown: 1, codes: 1 });
	});

	it('shows an IBAN in groups of four', () => {
		expect(shown({ kind: 'iban', value: 'DE89370400440532013000' })).toBe(
			'DE89 3704 0044 0532 0130 00'
		);
		expect(shown({ kind: 'customer_number', value: '20047718' })).toBe('20047718');
	});

	it('finds the content of a code in the text', () => {
		const code = FACTS.codes![0];
		expect(codeSpans(FACTS, code)).toEqual([
			{ start: 20, end: 47, locations: [] },
			{ start: 0, end: 10, locations: [] }
		]);
	});

	it('finds a quote however its lines and spaces fall, case aside', () => {
		const text = 'Rechnung   Nr. 4711\nGesamtbetrag      84,20 EUR\n\fgesamtbetrag 84,20 eur';
		const found = quoteStretches(text, ' Gesamtbetrag 84,20 EUR ');
		expect(found.map((stretch) => text.slice(stretch.start, stretch.end))).toEqual([
			'Gesamtbetrag      84,20 EUR',
			'gesamtbetrag 84,20 eur'
		]);
		// Its marks stand for themselves; at most a few places.
		expect(quoteStretches(text, 'Nr. 4711 Gesamtbetrag')).toEqual([{ start: 11, end: 32 }]);
		expect(quoteStretches(text, 'Nr 4711')).toEqual([]);
		expect(quoteStretches('a a a a a a a', 'a', 3)).toHaveLength(3);
		expect(quoteStretches(text, '  ')).toEqual([]);
	});

	it('marks a fact on each page it stands on, under its label', () => {
		const box = { x: 0.1, y: 0.2, width: 0.3, height: 0.01 };
		const spans = [
			{
				start: 0,
				end: 10,
				locations: [
					{ page: 1, boxes: [box] },
					{ page: 2, boxes: [box, box] }
				]
			},
			{ start: 40, end: 50, locations: [] }
		];
		expect(spanMarks(spans, 'IBAN')).toEqual([
			{ key: 'fact:0', label: 'IBAN', page: 1, boxes: [box], derived: false, pinned: false },
			{ key: 'fact:0', label: 'IBAN', page: 2, boxes: [box, box], derived: false, pinned: false }
		]);
	});
});

describe('the persons a document names', () => {
	it('says how surely and by what', () => {
		expect(strengthLabel('hard')).toBe(m.facts_person_hard());
		expect(strengthLabel('weak')).toBe(m.facts_person_weak());
		expect(['tax_id', 'birth_date', 'alias', 'name'].map(evidenceLabel)).toEqual([
			m.identifier_kind_tax_id(),
			m.facts_person_birth_date(),
			m.facts_person_alias(),
			m.facts_person_name()
		]);
	});
});
