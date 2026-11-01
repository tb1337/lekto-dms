import { afterEach, describe, expect, it } from 'vitest';
import {
	shortIdOf,
	keepsForm,
	fieldEvidence,
	byPage,
	inboxDocument,
	keepPlace,
	marksOf,
	neighbours,
	nextDecision,
	type InboxPlace,
	pageHref,
	pageOf,
	placesApply,
	provenance,
	stepHref,
	stepOf,
	tabHref,
	tabOf,
	viewerSources,
	viewHref,
	viewOf,
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
	it('come from the URL, the document without one', () => {
		expect(tabOf(new URL('http://lekto/ui/documents/1'))).toBe('document');
		expect(tabOf(new URL('http://lekto/ui/documents/1?tab=processing'))).toBe('processing');
		// The tabs of before 0.6 by their names of now.
		expect(tabOf(new URL('http://lekto/ui/documents/1?tab=log'))).toBe('processing');
		expect(tabOf(new URL('http://lekto/ui/documents/1?tab=metadata'))).toBe('properties');
		expect(tabOf(new URL('http://lekto/ui/documents/1?tab=nonsense'))).toBe('document');
		// Names an object has by itself are no tabs.
		expect(tabOf(new URL('http://lekto/ui/documents/1?tab=toString'))).toBe('document');
		expect(tabOf(new URL('http://lekto/ui/documents/1?tab=constructor'))).toBe('document');
		// The tabs of before are the document's.
		expect(tabOf(new URL('http://lekto/ui/documents/1?tab=content'))).toBe('document');
	});

	it('keep the other parameters', () => {
		const url = new URL(
			'http://lekto/ui/documents/1?from=inbox&tab=processing&left=text&right=form'
		);
		expect(tabHref(url, 'properties')).toBe(
			'/ui/documents/1?from=inbox&tab=properties&left=text&right=form'
		);
		expect(tabHref(url, 'document')).toBe('/ui/documents/1?from=inbox&left=text&right=form');
		expect(tabHref(new URL('http://lekto/ui/documents/1?tab=processing'), 'document')).toBe(
			'/ui/documents/1'
		);
	});

	it('keep the step only on the processing tab', () => {
		const url = new URL('http://lekto/ui/documents/1?tab=processing&step=judge');
		expect(tabHref(url, 'document')).toBe('/ui/documents/1');
		expect(tabHref(url, 'properties')).toBe('/ui/documents/1?tab=properties');
		expect(tabHref(url, 'processing')).toBe('/ui/documents/1?tab=processing&step=judge');
		expect(viewHref(url, { left: 'pages', right: 'form' })).toBe(
			'/ui/documents/1?left=pages&right=form'
		);
	});
});

describe('the step of the processing tab', () => {
	it('comes from the URL when the graph knows it', () => {
		const url = new URL('http://lekto/ui/documents/1?tab=processing&step=judge');
		expect(stepOf(url, ['ocr', 'judge'])).toBe('judge');
		expect(stepOf(url, ['ocr'])).toBeNull();
		expect(stepOf(new URL('http://lekto/ui/documents/1?tab=processing'), ['ocr'])).toBeNull();
	});

	it('goes into the link of the processing tab, keeping the other parameters', () => {
		const url = new URL('http://lekto/ui/documents/1?from=inbox&tab=processing');
		expect(stepHref(url, 'ocr')).toBe('/ui/documents/1?from=inbox&tab=processing&step=ocr');
		expect(stepHref(new URL('http://lekto/ui/documents/1?step=ocr&tab=processing'), null)).toBe(
			'/ui/documents/1?tab=processing'
		);
	});
});

describe('the view of the document tab', () => {
	afterEach(() => localStorage.clear());

	it('comes from the URL, a link of before, else checks: nothing is remembered', () => {
		const at = (query: string) => new URL(`http://lekto/ui/documents/1${query}`);
		const reading = { left: 'text', right: 'facts' } as const;
		// What an earlier version kept in the browser counts no more.
		localStorage.setItem('lekto.document.view', JSON.stringify(reading));
		expect(viewOf(at(''))).toEqual({ left: 'pages', right: 'form' });
		expect(viewOf(at('?left=text&right=form'))).toEqual({ left: 'text', right: 'form' });
		expect(viewOf(at('?tab=content'))).toEqual(reading);
		expect(viewOf(at('?tab=details'))).toEqual({ left: 'pages', right: 'form' });
		expect(viewOf(at('?tab=content&right=form'))).toEqual({ left: 'text', right: 'form' });
		expect(viewOf(at('?left=nonsense&right=facts'))).toEqual({ left: 'pages', right: 'facts' });
	});

	it('shows a page a link asks for, then forgets it', () => {
		const url = new URL('http://lekto/ui/documents/1?from=inbox&tab=processing&step=pages');
		const href = pageHref(url, 3);
		expect(href).toBe('/ui/documents/1?from=inbox&left=pages&right=form&page=3');
		expect(pageOf(new URL(`http://lekto${href}`))).toBe(3);
		expect(pageHref(new URL(`http://lekto${href}`), null)).toBe(
			'/ui/documents/1?from=inbox&left=pages&right=form'
		);
		expect(pageOf(new URL('http://lekto/ui/documents/1?page=0'))).toBeNull();
		expect(pageOf(new URL('http://lekto/ui/documents/1?page=x'))).toBeNull();
	});

	it('keeps the form while only the view of the same document changes', () => {
		const at = (href: string) => new URL(`http://lekto/ui/documents/${href}`);
		expect(keepsForm(at('1?from=inbox'), at('1?from=inbox&left=text&right=form'))).toBe(true);
		expect(keepsForm(at('1?left=text&right=form'), at('1?left=pages&right=facts&page=2'))).toBe(
			true
		);
		expect(keepsForm(at('1'), at('1?tab=properties'))).toBe(false);
		expect(keepsForm(at('1'), at('2'))).toBe(false);
	});

	it('is linked, leaving a tab of before behind', () => {
		const url = new URL('http://lekto/ui/documents/1?from=inbox&tab=content');
		expect(viewHref(url, { left: 'pages', right: 'facts' })).toBe(
			'/ui/documents/1?from=inbox&left=pages&right=facts'
		);
	});
});

describe('fieldEvidence', () => {
	it('prefers the open checks to those of the latest runs', () => {
		const review = {
			document: {},
			open: [
				{
					node: 'judge',
					outcome: 'uncertain',
					reason: 'x',
					fields: [check('contact', { outcome: 'uncertain' })]
				}
			],
			nodes: [
				{
					node: 'judge',
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
		// Not among them: no neighbours, back to the inbox after confirming.
		expect(neighbours(['a', 'b'], 'x')).toEqual({
			position: null,
			total: 2,
			previous: null,
			next: null
		});
		expect(inboxDocument('a')).toBe('/ui/documents/a?from=inbox');
	});
});

describe('the place in the inbox', () => {
	const at = (id: string, tab: InboxPlace['tab'] = 'new'): InboxPlace => ({ id, tab });

	it('keeps the open document where it stood once it left the inbox', () => {
		const before = [at('a'), at('b'), at('c'), at('d')];
		expect(keepPlace(before, [at('a'), at('c'), at('d')], 'b')).toEqual(before);
		// The ones before it left too: first.
		expect(keepPlace(before, [at('d')], 'c').map((place) => place.id)).toEqual(['c', 'd']);
		expect(keepPlace(before, [at('c')], 'a').map((place) => place.id)).toEqual(['a', 'c']);
	});

	it('takes the inbox as it is otherwise', () => {
		expect(keepPlace([], [at('a')], 'x')).toEqual([at('a')]);
		expect(keepPlace([at('x')], [at('a'), at('x', 'review')], 'x')).toEqual([
			at('a'),
			at('x', 'review')
		]);
		// Another document left: gone.
		expect(keepPlace([at('a'), at('b')], [at('b')], 'b')).toEqual([at('b')]);
	});

	it('offers next the document that waits for a decision, never a new one or one in processing', () => {
		const places = [
			at('r1', 'intervene'),
			at('me', 'review'),
			at('n1', 'new'),
			at('p1', 'processing'),
			at('y1', 'review'),
			at('r2', 'intervene')
		];
		expect(nextDecision(places, 'me')).toBe('y1');
		// From the last one on, the first before it.
		expect(nextDecision(places, 'r2')).toBe('r1');
		expect(nextDecision([at('me', 'review'), at('n1'), at('p1', 'processing')], 'me')).toBeNull();
		expect(nextDecision([], 'me')).toBeNull();
		// Not (or no longer) in the inbox: the first that waits.
		expect(nextDecision([at('n1'), at('y1', 'review')], 'gone')).toBe('y1');
	});
});

describe('places by page', () => {
	it('makes one place per page with every box on it, in page order', () => {
		const box = (y: number) => ({ x: 0.1, y, width: 0.2, height: 0.02 });
		expect(
			byPage([
				{ page: 9, boxes: [box(0.1)] },
				{ page: 1, boxes: [box(0.2)] },
				{ page: 9, boxes: [box(0.5), box(0.52)] }
			])
		).toEqual([
			{ page: 1, boxes: [box(0.2)] },
			{ page: 9, boxes: [box(0.1), box(0.5), box(0.52)] }
		]);
	});
});

describe('viewerSources', () => {
	const pdf = { id: 'd1', media_type: 'application/pdf', page_count: null };
	const image = { id: 'd2', media_type: 'image/png', page_count: null };

	it('shows the archive once it exists', () => {
		expect(viewerSources(pdf, true)).toEqual(['/api/v1/documents/d1/archive']);
		expect(viewerSources(image, true)).toEqual(['/api/v1/documents/d2/archive']);
	});

	it('asks for no archive before it can exist', () => {
		expect(viewerSources(pdf, false)).toEqual(['/api/v1/documents/d1/original']);
		expect(viewerSources(image, false)).toEqual([]);
	});
});

describe('a short id', () => {
	it('is the end of an id an assistant links a document by', () => {
		expect(shortIdOf('9B653410')).toBe('9b653410');
		expect(shortIdOf('54229b653410')).toBe('54229b653410');
		expect(shortIdOf('01a19889-c51a-7602-b24a-54229b653410')).toBeNull();
		expect(shortIdOf('1234')).toBeNull();
		expect(shortIdOf('9b65341x')).toBeNull();
	});
});
