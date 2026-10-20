import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Facts } from '#lib/facts.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import DocumentContent from './DocumentContent.svelte';

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

describe('DocumentContent', () => {
	it('shows the text as it is set, page by page', async () => {
		render(DocumentContent, { documentId: 'doc-1' });
		const first = await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		const second = screen.getByRole('region', { name: m.content_page({ page: 2 }) });
		// Columns stay where they are set: no Markdown, no collapsed spaces.
		expect(first.querySelector('pre')?.textContent).toBe(
			'Gesamtbrutto (EBeschV)      6.767,00\nSteuer-Brutto, EZ           3.544,50'
		);
		expect(within(second).getByText('Seite zwei')).toBeTruthy();
		// The text alone: no switch to its structure any more.
		expect(screen.queryByRole('group')).toBeNull();
		// Without facts yet, their card says when they come.
		expect(screen.getByText(m.facts_pending())).toBeTruthy();
	});

	it('asks for no text before the document has it', async () => {
		render(DocumentContent, { documentId: 'doc-1', hasText: false });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(fetchMock).not.toHaveBeenCalled();
		expect(screen.queryByRole('region', { name: m.content_page({ page: 1 }) })).toBeNull();
		expect(screen.queryByText(m.loading())).toBeNull();
	});

	it('marks a fact where it stands in the text', async () => {
		const scrolled = vi.fn();
		Element.prototype.scrollIntoView = scrolled;
		const facts: Facts = {
			contact_id: null,
			named: [],
			identifiers: [
				{
					kind: 'customer_number',
					value: 'EBeschV',
					contact_id: null,
					in_text: true,
					in_code: false,
					spans: [{ start: 14, end: 21 }],
					other_contacts: null
				}
			],
			codes: []
		};
		const lookup = { contacts: [], fields: [] } as unknown as Lookup;
		render(DocumentContent, { documentId: 'doc-1', facts, lookup });
		await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		const panel = screen.getByRole('complementary', { name: m.facts_title() });
		await fireEvent.click(within(panel).getByRole('button', { name: /EBeschV/ }));
		const marked = document.querySelector('mark[data-mark]');
		expect(marked?.textContent).toBe('EBeschV');
		expect(scrolled).toHaveBeenCalled();
	});
});
