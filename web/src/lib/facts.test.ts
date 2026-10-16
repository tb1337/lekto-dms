import { describe, expect, it } from 'vitest';
import {
	codeSpans,
	factCounts,
	grouped,
	inUnits,
	pageRanges,
	segmentsOf,
	shown,
	type Facts
} from './facts.ts';

const CONTACT = 'contact-1';

const FACTS: Facts = {
	contact_id: CONTACT,
	named: [
		{
			contact_id: CONTACT,
			name: 'Papiq Test GmbH',
			alias: false,
			in_text: true,
			in_code: true,
			spans: [{ start: 0, end: 10 }]
		}
	],
	identifiers: [
		{
			kind: 'iban',
			value: 'DE89370400440532013000',
			contact_id: CONTACT,
			in_text: true,
			in_code: true,
			spans: [{ start: 20, end: 47 }],
			other_contacts: null
		},
		{
			kind: 'vat_id',
			value: 'DE312456789',
			contact_id: 'contact-2',
			in_text: true,
			in_code: false,
			spans: [],
			other_contacts: null
		},
		{
			kind: 'customer_number',
			value: '20047718',
			contact_id: null,
			in_text: true,
			in_code: false,
			spans: [{ start: 60, end: 69 }],
			other_contacts: 0
		}
	],
	codes: [
		{
			format: 'QR Code',
			text: 'BCD',
			places: [{ page: 1, boxes: [{ x: 0.7, y: 0.8, width: 0.1, height: 0.1 }] }],
			giro: {
				name: 'Papiq Test GmbH',
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
			'Papiq Test GmbH',
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
			{ start: 20, end: 47 },
			{ start: 0, end: 10 }
		]);
	});
});
