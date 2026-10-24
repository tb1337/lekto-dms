import { render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { events } from '#lib/events.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import DocumentText from './DocumentText.svelte';

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

const TEXT =
	'Gesamtbrutto (EBeschV)      6.767,00\nSteuer-Brutto, EZ           3.544,50\n\f\nSeite zwei';

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () =>
		Response.json({ text: TEXT, offset: 0, total_length: TEXT.length, next_offset: null })
	);
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('DocumentText', () => {
	it('reads the text again only when its node has read it again', async () => {
		// Issue #75: of a run's events only the text's node changes the text.
		const listeners = new Map<string, (message: { data: string }) => void>();
		events.useFactory(
			() =>
				({
					addEventListener(type: string, handler: (message: { data: string }) => void) {
						listeners.set(type, handler);
					},
					close() {}
				}) as unknown as EventSource
		);
		events.start(() => {});
		const completed = (node: string) =>
			listeners.get('document.node_completed')?.({
				data: JSON.stringify({
					type: 'document.node_completed',
					id: node,
					occurred_at: '',
					document_id: 'doc-1',
					node,
					run: 1,
					outcome: 'ok'
				})
			});
		render(DocumentText, { documentId: 'doc-1' });
		await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		for (const node of ['ocr', 'pages', 'signal_llm', 'judge']) completed(node);
		expect(fetchMock).toHaveBeenCalledTimes(1);
		completed('parse');
		expect(fetchMock).toHaveBeenCalledTimes(2);
		events.stop();
	});

	it('shows the text as it is set, page by page', async () => {
		render(DocumentText, { documentId: 'doc-1' });
		const first = await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		const second = screen.getByRole('region', { name: m.content_page({ page: 2 }) });
		// Columns stay where they are set: no Markdown, no collapsed spaces.
		expect(first.querySelector('pre')?.textContent).toBe(
			'Gesamtbrutto (EBeschV)      6.767,00\nSteuer-Brutto, EZ           3.544,50'
		);
		expect(within(second).getByText('Seite zwei')).toBeTruthy();
		// The text alone: no switch to its structure any more.
		expect(screen.queryByRole('group')).toBeNull();
	});

	it('asks for no text before the document has it', async () => {
		render(DocumentText, { documentId: 'doc-1', hasText: false });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(fetchMock).not.toHaveBeenCalled();
		expect(screen.queryByRole('region', { name: m.content_page({ page: 1 }) })).toBeNull();
		expect(screen.queryByText(m.loading())).toBeNull();
	});

	it('marks what it is given, and scrolls there when asked', async () => {
		const scrolled = vi.fn();
		Element.prototype.scrollIntoView = scrolled;
		const view = render(DocumentText, {
			documentId: 'doc-1',
			marks: [{ start: 14, end: 21 }]
		});
		await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		expect(document.querySelector('mark[data-mark]')?.textContent).toBe('EBeschV');
		await view.component.revealMark();
		expect(scrolled).toHaveBeenCalled();
	});

	it('tells the page in the upper third of what is seen', async () => {
		// Page 1 has gone up, page 2 starts above the line a third down the window, page 3 below.
		const tops: Record<string, number> = { '1': -500, '2': 100, '3': 900 };
		vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (
			this: Element
		) {
			const page = (this as HTMLElement).dataset?.page;
			const top = page ? tops[page] : 0;
			return { top, bottom: page ? top + 400 : 800, left: 0, right: 400 } as DOMRect;
		});
		fetchMock.mockImplementation(async () =>
			Response.json({
				text: 'eins\n\f\nzwei\n\f\ndrei',
				offset: 0,
				total_length: 17,
				next_offset: null
			})
		);
		const onpage = vi.fn();
		render(DocumentText, { documentId: 'doc-1', onpage });
		await screen.findByRole('region', { name: m.content_page({ page: 3 }) });
		window.dispatchEvent(new Event('scroll'));
		await vi.waitFor(() => expect(onpage).toHaveBeenLastCalledWith(2, 3));
	});

	it('marks the quotes it is given where they stand, however their spaces fall', async () => {
		render(DocumentText, {
			documentId: 'doc-1',
			marks: [{ start: 14, end: 21 }],
			quotes: ['Steuer-Brutto, EZ 3.544,50', 'nicht im Text']
		});
		await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		const marked = [...document.querySelectorAll('mark[data-mark]')].map(
			(mark) => mark.textContent
		);
		expect(marked).toEqual(['EBeschV', 'Steuer-Brutto, EZ           3.544,50']);
	});
});
