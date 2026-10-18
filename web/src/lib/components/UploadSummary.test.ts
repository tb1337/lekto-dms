import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { json } from '#lib/testing/documents.ts';
import { uploads } from '#lib/upload.svelte.ts';
import UploadSummary from './UploadSummary.svelte';

const pdf = (name: string) => ({
	file: new File(['%PDF-1.7'], name, { type: 'application/pdf' }),
	name
});

beforeEach(() => {
	session.start({
		user: { id: 'user-1', username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-18T12:00:00Z',
		csrf_token: 'token'
	});
});

afterEach(() => {
	uploads.reset();
	session.clear();
	vi.unstubAllGlobals();
});

describe('UploadSummary', () => {
	it('sums up what came of the uploads and stays until dismissed', async () => {
		const answers = [
			json({ id: 'doc-1' }, 202),
			json({ id: 'doc-2' }, 202),
			json(
				{ type: 'about:blank', title: 'Conflict', status: 409, existing_document_id: 'doc-old' },
				409
			)
		];
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => answers.shift()!)
		);
		render(UploadSummary);
		uploads.add({
			files: [pdf('a.pdf'), pdf('b.pdf'), pdf('twin.pdf')],
			skipped: [
				{ name: 'notes.txt', reason: 'type' },
				{ name: 'Scans/.DS_Store', reason: 'hidden' }
			]
		});
		const summary = await screen.findByRole('region', { name: m.upload_summary_label() });
		await waitFor(() =>
			expect(
				within(summary).getByText(
					[
						m.upload_summary_uploaded({ count: 2 }),
						m.upload_summary_duplicate(),
						m.upload_summary_skipped({ count: 2 })
					].join(', ')
				)
			).toBeTruthy()
		);
		const twin = within(summary).getByText('twin.pdf').closest('li')!;
		expect(within(twin).getByText(m.upload_duplicate())).toBeTruthy();
		expect(within(twin).getByRole('link', { name: m.upload_existing() }).getAttribute('href')).toBe(
			'/ui/documents/doc-old'
		);
		const hidden = within(summary).getByText('Scans/.DS_Store').closest('li')!;
		expect(within(hidden).getByText(m.upload_skipped_hidden())).toBeTruthy();
		expect(
			within(within(summary).getByText('notes.txt').closest('li')!).getByText(
				m.upload_skipped_type()
			)
		).toBeTruthy();
		// The uploaded ones stand in the inbox; the summary does not list them.
		expect(within(summary).queryByText('a.pdf')).toBeNull();

		// It stays (nothing takes it away by itself) until dismissed.
		await new Promise((resolve) => setTimeout(resolve, 50));
		expect(screen.getByRole('region', { name: m.upload_summary_label() })).toBeTruthy();
		await userEvent.click(within(summary).getByRole('button', { name: m.upload_dismiss() }));
		expect(screen.queryByRole('region', { name: m.upload_summary_label() })).toBeNull();
	});

	it('shows the progress while files are on their way', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(() => new Promise<Response>(() => {}))
		);
		render(UploadSummary);
		uploads.add({ files: [pdf('a.pdf'), pdf('b.pdf')], skipped: [] });
		const summary = await screen.findByRole('region', { name: m.upload_summary_label() });
		expect(within(summary).getByText(m.upload_running({ done: 0, total: 2 }))).toBeTruthy();
		expect(within(summary).getByRole('progressbar')).toBeTruthy();
		expect(
			(within(summary).getByRole('button', { name: m.upload_dismiss() }) as HTMLButtonElement)
				.disabled
		).toBe(true);
	});
});
