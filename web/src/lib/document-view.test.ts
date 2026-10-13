import { describe, expect, it } from 'vitest';
import {
	fieldEvidence,
	marksOf,
	neighbours,
	placesApply,
	provenance,
	tabHref,
	tabOf,
	type Check,
	type Review
} from './document-view.ts';

function check(field: string, changes: Partial<Check> = {}): Check {
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
		...changes
	};
}

const place = { page: 2, boxes: [{ x: 0.1, y: 0.5, width: 0.2, height: 0.02 }] };

describe('tabs', () => {
	it('come from the URL, the details without one', () => {
		expect(tabOf(new URL('http://papiq/ui/documents/1'))).toBe('details');
		expect(tabOf(new URL('http://papiq/ui/documents/1?tab=log'))).toBe('log');
		expect(tabOf(new URL('http://papiq/ui/documents/1?tab=nonsense'))).toBe('details');
	});

	it('keep the other parameters', () => {
		const url = new URL('http://papiq/ui/documents/1?from=inbox&tab=log');
		expect(tabHref(url, 'content')).toBe('/ui/documents/1?from=inbox&tab=content');
		expect(tabHref(url, 'details')).toBe('/ui/documents/1?from=inbox');
		expect(tabHref(new URL('http://papiq/ui/documents/1?tab=log'), 'details')).toBe(
			'/ui/documents/1'
		);
	});
});

describe('fieldEvidence', () => {
	it('prefers the open checks to those of the latest runs', () => {
		const review = {
			document: {},
			open: [
				{
					node: 'classify',
					outcome: 'uncertain',
					reason: 'x',
					fields: [check('contact', { outcome: 'uncertain' })]
				}
			],
			nodes: [
				{
					node: 'classify',
					run: 1,
					outcome: 'uncertain',
					reason: 'x',
					model_version: 'm',
					truncated: false,
					fields: [check('contact'), check('document_date', { evidence: '31.03.2026' })]
				}
			]
		} as unknown as Review;
		const found = fieldEvidence(review);
		expect(found.get('contact')).toEqual({
			check: check('contact', { outcome: 'uncertain' }),
			open: true
		});
		expect(found.get('document_date')?.open).toBe(false);
		expect(fieldEvidence(null).size).toBe(0);
	});
});

describe('provenance', () => {
	it('tells a quote from one the value follows from and from none', () => {
		expect(provenance(check('contact', { evidence: 'Stadtwerke', quote_shows_value: true }))).toBe(
			'quote'
		);
		expect(provenance(check('field:1', { evidence: 'Zahlbar bis 15.04.' }))).toBe('quote');
		expect(
			provenance(check('contact', { evidence: 'Kundennummer 4711', quote_shows_value: false }))
		).toBe('derived');
		expect(provenance(check('tags', { evidence: '  ' }))).toBe('none');
	});
});

describe('placesApply', () => {
	it('only while the value is the one checked or suggested', () => {
		const dated = check('document_date', { value: '2026-03-31' });
		expect(placesApply(dated, '2026-03-31')).toBe(true);
		expect(placesApply(dated, '2026-04-01')).toBe(false);
		const amount = check('field:1', {
			outcome: 'uncertain',
			suggestion: { amount: '84.20', currency: 'EUR' }
		});
		expect(placesApply(amount, { amount: '84.20', currency: 'EUR' })).toBe(true);
		expect(placesApply(amount, null)).toBe(false);
		expect(placesApply(check('field:2'), 'anything')).toBe(true);
		expect(placesApply(check('tags', { value: ['a', 'b'] }), ['b', 'a'])).toBe(true);
	});
});

describe('marksOf', () => {
	it('draws each place, dashed for a derived quote', () => {
		const derived = check('contact', {
			evidence: 'Kundennummer 4711',
			quote_shows_value: false,
			locations: [place]
		});
		expect(marksOf('contact', 'Kontakt', derived, { pinned: true })).toEqual([
			{ key: 'contact', label: 'Kontakt', ...place, derived: true, pinned: true }
		]);
		expect(marksOf('contact', 'Kontakt', check('contact'))).toEqual([]);
	});
});

describe('neighbours', () => {
	it('names the documents before and after', () => {
		expect(neighbours(['a', 'b', 'c'], 'b')).toEqual({
			position: 2,
			total: 3,
			previous: 'a',
			next: 'c'
		});
		expect(neighbours(['a', 'b'], 'a')).toEqual({
			position: 1,
			total: 2,
			previous: null,
			next: 'b'
		});
		// Confirmed meanwhile: it left the inbox, the first one is next.
		expect(neighbours(['a', 'b'], 'x')).toEqual({
			position: null,
			total: 2,
			previous: null,
			next: 'a'
		});
	});
});
