import { render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
		render(DocumentContent, { documentId: 'doc-1', filename: 'payslip.pdf' });
		const first = await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		const second = screen.getByRole('region', { name: m.content_page({ page: 2 }) });
		// Columns stay where they are set: no Markdown, no collapsed spaces.
		expect(first.querySelector('pre')?.textContent).toBe(
			'Gesamtbrutto (EBeschV)      6.767,00\nSteuer-Brutto, EZ           3.544,50'
		);
		expect(within(second).getByText('Seite zwei')).toBeTruthy();
		const views = screen.getByRole('group', { name: m.content_view() });
		expect(
			within(views)
				.getAllByRole('button')
				.map((button) => button.textContent?.trim())
		).toEqual([m.content_text(), m.content_json()]);
	});
});
