import { render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

afterEach(() => vi.unstubAllGlobals());

describe('DocumentText', () => {
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
