import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { toast } from 'svelte-sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import { m } from '#lib/paraglide/messages.js';
import { documentOf, fakeApi } from '#lib/testing/documents.ts';
import { goTo } from '#lib/testing/page-state.svelte.ts';
import Beam from './Beam.svelte';

vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

const LIST = '/ui/documents?tag=t1';
const beam = (index: number) => ({ ids: ['a', 'b'], index, from: 'Dokumente' });

beforeEach(() => {
	vi.mocked(goto).mockClear();
	vi.stubGlobal(
		'IntersectionObserver',
		class {
			observe() {}
			unobserve() {}
			disconnect() {}
		}
	);
	vi.stubGlobal(
		'fetch',
		fakeApi({
			'GET /api/v1/documents/a': () =>
				documentOf({
					id: 'a',
					title: 'Stromrechnung März',
					contact_id: 'c1',
					document_type_id: 't1',
					document_date: '2026-03-31',
					page_count: 2
				}),
			'GET /api/v1/documents/b': () => new Response(null, { status: 404 }),
			'GET /api/v1/contacts/c1': () => ({ id: 'c1', name: 'Stadtwerke' }),
			'GET /api/v1/document-types/t1': () => ({ id: 't1', name: 'Rechnung' })
		})
	);
});

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	goTo('/ui/inbox');
});

describe('Beam', () => {
	it('stays closed without a Beam in the history entry', () => {
		goTo(LIST);
		render(Beam);
		expect(screen.queryByRole('dialog')).toBeNull();
	});

	it('shows the pages of the document with its head, and pages through the documents', async () => {
		goTo(LIST, {}, { words: 'Strom', beam: beam(0) });
		render(Beam);
		const sheet = await screen.findByRole('dialog', { name: 'Stromrechnung März' });
		expect(sheet.textContent).toContain(m.beam_name());
		await waitFor(() => expect(sheet.textContent).toContain('Stadtwerke · Rechnung'));
		expect(sheet.textContent).toContain(m.beam_position({ current: 1, total: 2 }));
		const pages = await screen.findAllByRole('img');
		expect(pages.map((image) => image.getAttribute('src'))).toEqual([
			'/api/v1/documents/a/pages/1',
			'/api/v1/documents/a/pages/2'
		]);
		expect(screen.getByRole('button', { name: m.beam_previous() })).toHaveProperty(
			'disabled',
			true
		);
		// The next one in the same history entry, the words kept.
		await userEvent.click(screen.getByRole('button', { name: m.beam_next() }));
		expect(goto).toHaveBeenLastCalledWith('http://lekto/ui/documents?tag=t1', {
			shallow: true,
			replace: true,
			state: { words: 'Strom', beam: beam(1) },
			persistState: true
		});
		// The arrow keys do the same.
		await fireEvent.keyDown(sheet, { key: 'ArrowRight' });
		expect(goto).toHaveBeenCalledTimes(2);
	});

	it('opens the document with the way back to the place', async () => {
		goTo(LIST, {}, { beam: beam(0) });
		render(Beam);
		await screen.findByRole('dialog', { name: 'Stromrechnung März' });
		await userEvent.click(screen.getByRole('button', { name: m.beam_open_document() }));
		expect(goto).toHaveBeenLastCalledWith('/ui/documents/a', {
			state: { from: { label: 'Dokumente' } },
			persistState: true
		});
	});

	it('opens a document of the inbox there, with its neighbours', async () => {
		goTo('/ui/inbox', {}, { beam: { ...beam(0), from: 'Eingang', inbox: true } });
		render(Beam);
		await screen.findByRole('dialog', { name: 'Stromrechnung März' });
		await userEvent.click(screen.getByRole('button', { name: m.beam_open_document() }));
		expect(goto).toHaveBeenLastCalledWith('/ui/documents/a?from=inbox', {
			state: { from: { label: 'Eingang' } },
			persistState: true
		});
	});

	it('closes when its document is gone, and says so', async () => {
		const info = vi.spyOn(toast, 'info');
		goTo(LIST, {}, { words: 'Strom', beam: beam(1) });
		render(Beam);
		await waitFor(() => expect(info).toHaveBeenCalledWith(m.beam_gone()));
		// Restored by a reload, not pushed by this page: the entry loses the Beam, keeps the rest.
		expect(goto).toHaveBeenLastCalledWith('http://lekto/ui/documents?tag=t1', {
			shallow: true,
			replace: true,
			state: { words: 'Strom' },
			persistState: true
		});
	});
});
