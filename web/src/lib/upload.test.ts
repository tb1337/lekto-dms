import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { intakeOf } from '#lib/intake.ts';
import { session } from '#lib/session.svelte.ts';
import { json } from '#lib/testing/documents.ts';
import { PARALLEL, Uploads } from './upload.svelte.ts';

const pdf = (name: string) => new File(['%PDF-1.7'], name, { type: 'application/pdf' });

function problem(status: number, extra: Record<string, unknown> = {}): Response {
	return json({ type: 'about:blank', title: 'Problem', status, detail: 'no', ...extra }, status);
}

/** A fetch whose answers to the uploads wait until `answer` is called, in order. */
function held() {
	const waiting: ((response: Response) => void)[] = [];
	const requests: Request[] = [];
	const fetchMock = vi.fn((request: Request) => {
		requests.push(request);
		return new Promise<Response>((resolve) => waiting.push(resolve));
	});
	return {
		fetchMock,
		requests,
		get inFlight() {
			return waiting.length;
		},
		async answer(response: Response) {
			await vi.waitFor(() => expect(waiting.length).toBeGreaterThan(0));
			waiting.shift()!(response);
		}
	};
}

beforeEach(() => {
	session.start({
		user: { id: 'user-1', username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-18T12:00:00Z',
		csrf_token: 'token'
	});
});

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

describe('uploads', () => {
	it('sends a few at a time', async () => {
		const api = held();
		vi.stubGlobal('fetch', api.fetchMock);
		const uploads = new Uploads();
		uploads.add(intakeOf(['a', 'b', 'c', 'd', 'e'].map((name) => pdf(`${name}.pdf`))));
		await vi.waitFor(() => expect(api.inFlight).toBe(PARALLEL));
		expect(PARALLEL).toBe(3);
		expect(uploads.items.map((item) => item.state)).toEqual([
			'uploading',
			'uploading',
			'uploading',
			'waiting',
			'waiting'
		]);
		await api.answer(json({ id: 'doc-a' }, 202));
		await vi.waitFor(() => expect(api.fetchMock).toHaveBeenCalledTimes(4));
		expect(api.inFlight).toBe(PARALLEL);
		for (let index = 0; index < 4; index++) await api.answer(json({ id: `doc-${index}` }, 202));
		await vi.waitFor(() => expect(uploads.active).toBe(false));
		expect(uploads.counts).toMatchObject({ uploaded: 5, done: 5, total: 5 });
	});

	it('tells duplicates with the document already there, too large and foreign files', async () => {
		const answers = [
			json({ id: 'doc-new' }, 202),
			problem(409, { existing_document_id: 'doc-old' }),
			problem(409),
			problem(413),
			problem(415),
			problem(500)
		];
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => answers.shift()!)
		);
		const uploads = new Uploads();
		uploads.add({
			files: ['new', 'twin', 'unseen', 'huge', 'fake', 'broken'].map((name) => ({
				file: pdf(`${name}.pdf`),
				name: `${name}.pdf`
			})),
			skipped: [{ name: 'notes.txt', reason: 'type' }]
		});
		await vi.waitFor(() => expect(uploads.active).toBe(false));
		const byName = Object.fromEntries(uploads.items.map((item) => [item.name, item]));
		expect(byName['notes.txt']).toMatchObject({ state: 'skipped', reason: 'type' });
		expect(byName['new.pdf']).toMatchObject({ state: 'uploaded', documentId: 'doc-new' });
		expect(byName['twin.pdf']).toMatchObject({ state: 'duplicate', documentId: 'doc-old' });
		// Every file exists once: one in a space the caller cannot see comes without an id.
		expect(byName['unseen.pdf']).toMatchObject({ state: 'duplicate', documentId: null });
		expect(byName['huge.pdf']).toMatchObject({ state: 'skipped', reason: 'too_large' });
		expect(byName['fake.pdf']).toMatchObject({ state: 'skipped', reason: 'type' });
		expect(byName['broken.pdf']).toMatchObject({ state: 'failed', message: 'no' });
		expect(uploads.counts).toMatchObject({ uploaded: 1, duplicates: 2, skipped: 3, failed: 1 });
	});

	it('sends only the file: the document lands in the personal space', async () => {
		const api = held();
		vi.stubGlobal('fetch', api.fetchMock);
		// The forms as built (jsdom's files do not pass through the fetch of Node).
		const append = vi.spyOn(FormData.prototype, 'append');
		try {
			const uploads = new Uploads();
			uploads.add(intakeOf([pdf('a.pdf')]));
			uploads.add(intakeOf([pdf('b.pdf')]));
			await vi.waitFor(() => expect(api.requests).toHaveLength(2));
			expect(
				append.mock.calls.map(([name, value]) => [name, value instanceof File ? value.name : value])
			).toEqual([
				['file', 'a.pdf'],
				['file', 'b.pdf']
			]);
		} finally {
			append.mockRestore();
		}
	});

	it('forgets what is finished when dismissed, not what is on its way', async () => {
		const api = held();
		vi.stubGlobal('fetch', api.fetchMock);
		const uploads = new Uploads();
		uploads.add({
			files: [{ file: pdf('a.pdf'), name: 'a.pdf' }],
			skipped: [{ name: '.x', reason: 'hidden' }]
		});
		await vi.waitFor(() => expect(api.inFlight).toBe(1));
		uploads.dismiss();
		expect(uploads.items.map((item) => item.name)).toEqual(['a.pdf']);
		await api.answer(json({ id: 'doc-a' }, 202));
		await vi.waitFor(() => expect(uploads.active).toBe(false));
		uploads.dismiss();
		expect(uploads.items).toEqual([]);
	});
});
