import { render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import DocumentFiles from './DocumentFiles.svelte';

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

const SHA = 'a'.repeat(64);
const FILES = {
	added: '2026-07-03T08:40:36Z',
	modified: '2026-07-07T10:12:00Z',
	original_filename: 'scan-2026-07-03.pdf',
	media_type: 'application/pdf',
	page_count: 2,
	original: {
		size: 10_812_334,
		sha256: SHA,
		metadata: {
			format: 'PDF',
			pdf_version: '1.4',
			pdfa: null,
			pages: 2,
			width: null,
			height: null,
			dpi: null,
			entries: [{ source: 'info', key: 'Producer', value: 'Scanner 2.1' }]
		}
	},
	archive: null
};

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('DocumentFiles', () => {
	it('shows the file, the original with its metadata, and that there is no archive yet', async () => {
		fetchMock.mockImplementation(async () => Response.json(FILES));
		render(DocumentFiles, { documentId: 'doc-1' });
		const file = await screen.findByRole('region', { name: m.files_title() });
		expect(within(file).getByText('scan-2026-07-03.pdf')).toBeTruthy();
		const original = screen.getByRole('region', { name: m.files_original() });
		expect(within(original).getByText(SHA)).toBeTruthy();
		expect(within(original).getByText(/10[.,]8\s?MB/)).toBeTruthy();
		expect(within(original).getByText('1.4')).toBeTruthy();
		expect(within(original).getByText('Producer')).toBeTruthy();
		expect(within(original).getByText('Scanner 2.1')).toBeTruthy();
		expect(within(original).getByRole('button', { name: m.files_copy_hash() })).toBeTruthy();
		const archive = screen.getByRole('region', { name: m.files_archive() });
		expect(within(archive).getByText(m.files_no_archive())).toBeTruthy();
	});

	it('says when a file’s metadata cannot be read', async () => {
		fetchMock.mockImplementation(async () =>
			Response.json({ ...FILES, original: { ...FILES.original, metadata: null } })
		);
		render(DocumentFiles, { documentId: 'doc-1' });
		expect(await screen.findByText(m.files_unreadable())).toBeTruthy();
	});
});
