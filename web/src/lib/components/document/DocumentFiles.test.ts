import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatDate, formatNumber } from '#lib/i18n.ts';
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
	it('tells the life of the file and shows the original’s passport, without an archive yet', async () => {
		const original = {
			...FILES.original,
			metadata: {
				...FILES.original.metadata,
				entries: [
					{ source: 'info', key: 'Producer', value: 'Scanner 2.1' },
					{ source: 'info', key: 'CreationDate', value: "D:20260702173000+02'00'" }
				]
			}
		};
		fetchMock.mockImplementation(async () => Response.json({ ...FILES, original }));
		render(DocumentFiles, { documentId: 'doc-1' });
		const life = await screen.findByRole('list');
		expect(
			within(life)
				.getAllByRole('listitem')
				.map((step) => step.querySelector('.font-semibold')?.textContent?.trim())
		).toEqual([m.files_step_created(), m.files_step_added(), m.files_step_modified()]);
		expect(within(life).getByText(m.files_step_sender())).toBeTruthy();
		const passport = screen.getByRole('article', { name: m.files_original() });
		expect(within(passport).getByText(/10[.,]8\s?MB/)).toBeTruthy();
		expect(within(passport).getByText('PDF 1.4')).toBeTruthy();
		expect(within(passport).getByText(`${'a'.repeat(16)}…${'a'.repeat(8)}`)).toBeTruthy();
		expect(within(passport).getByRole('img', { name: m.files_fingerprint() })).toBeTruthy();
		expect(within(passport).getByText(m.files_made_with())).toBeTruthy();
		expect(within(passport).getAllByText('Scanner 2.1').length).toBeGreaterThan(0);
		expect(within(passport).getByRole('button', { name: m.files_copy_hash() })).toBeTruthy();
		const archive = screen.getByRole('region', { name: m.files_archive() });
		expect(within(archive).getByText(m.files_no_archive())).toBeTruthy();
	});

	it('lists every entry of the file chosen, to search, in columns that keep their width', async () => {
		const user = userEvent.setup();
		const archive = {
			size: 12_000_000,
			sha256: 'b'.repeat(64),
			metadata: {
				...FILES.original.metadata,
				pdfa: '2B',
				entries: [{ source: 'xmp', key: 'pdfaid:part', value: '2' }]
			}
		};
		fetchMock.mockImplementation(async () => Response.json({ ...FILES, archive }));
		render(DocumentFiles, { documentId: 'doc-1' });
		const table = await screen.findByRole('table');
		expect(table.querySelectorAll('col')).toHaveLength(3);
		expect(within(table).getByText('Producer')).toBeTruthy();
		expect(screen.getByText(m.files_size_more({ percent: '11' }))).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.files_archive() }));
		expect(within(table).getByText('pdfaid:part')).toBeTruthy();
		expect(within(table).queryByText('Producer')).toBeNull();
		await user.type(screen.getByLabelText(m.files_search()), 'nichts');
		expect(within(table).getByText(m.assignment_none_found())).toBeTruthy();
	});

	it('ends the life with a review still to come, and says how long lay between the steps', async () => {
		vi.useFakeTimers({ now: new Date('2026-07-09T10:12:00Z'), toFake: ['Date'] });
		fetchMock.mockImplementation(async () => Response.json(FILES));
		render(DocumentFiles, {
			documentId: 'doc-1',
			document: {
				lane: 'yellow',
				confirmed_at: null,
				channel: 'web',
				processing: { status: 'review', run: 1, vision: false, nodes: [] }
			}
		});
		const life = await screen.findByRole('list');
		const steps = within(life).getAllByRole('listitem');
		expect(steps.map((step) => step.querySelector('.font-semibold')?.textContent?.trim())).toEqual([
			m.files_step_added(),
			m.files_step_modified(),
			m.files_step_confirmed()
		]);
		const review = steps.at(-1)!;
		expect(within(review).getByText(m.files_step_pending())).toBeTruthy();
		expect(review.querySelector('time')).toBeNull();
		const days = (value: number) =>
			m.files_gap_after({
				duration: formatNumber(value, { style: 'unit', unit: 'day', unitDisplay: 'long' })
			});
		// Received to changed: four days; the review to come says since when instead.
		expect(within(steps[1]).getByText(days(4))).toBeTruthy();
		expect(within(review).queryByText(days(2))).toBeNull();
		expect(
			within(review).getByText(
				m.files_step_since({ date: formatDate(FILES.added, { dateStyle: 'medium' }) })
			)
		).toBeTruthy();
		vi.useRealTimers();
	});

	it('says when a file’s metadata cannot be read', async () => {
		fetchMock.mockImplementation(async () =>
			Response.json({ ...FILES, original: { ...FILES.original, metadata: null } })
		);
		render(DocumentFiles, { documentId: 'doc-1' });
		expect((await screen.findAllByText(m.files_unreadable())).length).toBeGreaterThan(0);
	});
});
