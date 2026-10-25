import { render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import StepDetails, { type DetailContext } from './StepDetails.svelte';

type LogEntry = components['schemas']['LogEntry'];

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

const JUKO = '0199a6c4-0000-7000-8000-0000000000c2';
const ANNA = '0199a6c4-0000-7000-8000-0000000000a1';
const lookup = {
	contacts: [{ id: JUKO, name: 'JUKO Marburg e.V.' }],
	documentTypes: [],
	tags: [],
	spaces: [],
	users: [{ id: ANNA, username: 'anna', display_name: 'Anna Leider' }]
} as unknown as Lookup;

const stored = (format: string, pdfa: string | null, size: number) => ({
	size,
	sha256: 'a'.repeat(64),
	metadata: {
		format,
		pdf_version: '1.7',
		pdfa,
		pages: 2,
		width: null,
		height: null,
		dpi: null,
		entries: []
	}
});

const context: DetailContext = {
	documentId: 'doc-1',
	latest: { ocr: 2, pages: 1, parse: 2 },
	files: {
		added: '2026-10-23T08:00:00Z',
		modified: '2026-10-23T08:00:00Z',
		original_filename: 'payslip.pdf',
		media_type: 'application/pdf',
		page_count: 2,
		original: stored('PDF', null, 373_000),
		archive: stored('PDF', '2B', 412_000)
	},
	poor: [2],
	thresholds: { contacts: 0.8 },
	textHref: '/ui/documents/doc-1?left=text&right=form',
	pageHref: (page) => `/ui/documents/doc-1?left=pages&right=form&page=${page}`
};

const entry = (node: string, run: number, output: Record<string, unknown>) =>
	({ node, run, output }) as unknown as LogEntry;

function json(body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'content-type': 'application/json' }
	});
}

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () =>
		json({ text: 'first\n\f\nsecond page', offset: 0, total_length: 18, next_offset: null })
	);
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('StepDetails', () => {
	it('shows the text recognition: the files, its notes and how well each page was read', () => {
		const { container } = render(StepDetails, {
			props: {
				entry: entry('ocr', 2, {
					pdfa: true,
					rgb: true,
					readings: [
						{ page: 1, words: 200, unsure: 4 },
						{ page: 2, words: 300, unsure: 60 }
					]
				}),
				lookup,
				context
			}
		});
		const files = screen.getByRole('group', { name: m.details_files() });
		expect(within(files).getByText('PDF/A-2B')).toBeTruthy();
		expect(within(files).getByText(m.files_original())).toBeTruthy();
		expect(screen.getByText(m.details_rgb())).toBeTruthy();
		expect(screen.getByText(m.details_reading())).toBeTruthy();
		// The poorly read page says so, for the eye and for a screen reader.
		expect(container.textContent).toContain(m.details_poor());
		expect(container.querySelectorAll('li[title]')).toHaveLength(2);
	});

	it('leaves the files out for a reading of an earlier run', () => {
		render(StepDetails, {
			props: {
				entry: entry('ocr', 1, { pdfa: true, readings: [{ page: 1, words: 10, unsure: 0 }] }),
				lookup,
				context
			}
		});
		expect(screen.queryByRole('group', { name: m.details_files() })).toBeNull();
		expect(screen.queryByText(m.details_poor())).toBeNull();
	});

	it('shows the page images, each a way to its page', () => {
		render(StepDetails, { props: { entry: entry('pages', 1, { pages: 2 }), lookup, context } });
		const second = screen.getByRole('link', { name: m.details_page_open({ page: '2' }) });
		expect(second.getAttribute('href')).toBe('/ui/documents/doc-1?left=pages&right=form&page=2');
		expect(second.querySelector('img')?.getAttribute('src')).toBe(
			'/api/v1/documents/doc-1/pages/2'
		);
	});

	it('counts the characters of each page and leads to the text', async () => {
		render(StepDetails, {
			props: {
				entry: entry('parse', 2, { pages: 2, characters: 18 }),
				lookup,
				context
			}
		});
		expect(screen.getByText(/18/)).toBeTruthy();
		expect(await screen.findByText(m.details_characters())).toBeTruthy();
		expect(screen.getByTitle(m.details_page_characters({ page: '2', count: '11' }))).toBeTruthy();
		expect(screen.getByRole('link', { name: m.details_text_open() }).getAttribute('href')).toBe(
			context.textHref
		);
	});

	it('asks for the text once, not again for every change of the processing view', async () => {
		const props = { entry: entry('parse', 2, { pages: 2, characters: 18 }), lookup, context };
		const { rerender } = render(StepDetails, { props });
		expect(await screen.findByText(m.details_characters())).toBeTruthy();
		expect(fetchMock).toHaveBeenCalledTimes(1);
		// The view builds its context anew on every change; the same document asks for nothing.
		await rerender({ ...props, context: { ...context, poor: [1] } });
		await rerender({ ...props, entry: entry('parse', 2, { pages: 2, characters: 18 }) });
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(fetchMock).toHaveBeenCalledTimes(1);
		// Another document: its text.
		await rerender({ ...props, context: { ...context, documentId: 'doc-2' } });
		await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
		expect(new URL(fetchMock.mock.calls[1][0].url).pathname).toBe('/api/v1/documents/doc-2/text');
	});

	it("draws the classifier's classes against its threshold", () => {
		const { container } = render(StepDetails, {
			props: {
				entry: entry('signal_classifier', 2, {
					contacts: [[JUKO, 0.56]],
					document_types: []
				}),
				lookup,
				context
			}
		});
		expect(screen.getByText('JUKO Marburg e.V.')).toBeTruthy();
		expect(screen.getByText('56%')).toBeTruthy();
		expect(container.textContent).toContain(m.details_threshold({ value: '80%' }));
		expect(screen.getByText(m.details_threshold_hint())).toBeTruthy();
	});

	it('loads no text for an earlier reading', async () => {
		render(StepDetails, {
			props: {
				entry: entry('parse', 1, { pages: 2, characters: 18 }),
				lookup,
				context
			}
		});
		await waitFor(() => expect(screen.getByText(/18/)).toBeTruthy());
		expect(fetchMock).not.toHaveBeenCalled();
		expect(screen.queryByRole('link', { name: m.details_text_open() })).toBeNull();
	});
});
