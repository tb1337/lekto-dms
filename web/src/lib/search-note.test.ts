import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PENDING_FOR, SearchNote, SLOW_AFTER } from './search-note.svelte.ts';

const timeout = { code: 'search_embed_timeout', params: { seconds: 5 } } as const;

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('search note', () => {
	it('keeps a search by words while the meaning is being made, until asked for it', () => {
		const note = new SearchNote();
		note.answered('Weihnachten', { mode: 'words', reason: timeout, meaning_pending: true });
		expect(note.about('Weihnachten')).toMatchObject({ pending: true, ready: false });
		expect(note.ratio('Weihnachten')).toBe(0);
		expect(note.ratio('Gehalt')).toBeUndefined();
		// A refresh by words keeps the hint.
		note.answered('Weihnachten', { mode: 'words', reason: null, meaning_pending: false });
		expect(note.about('Weihnachten')?.reason).toEqual(timeout);
		note.meaningReady('Gehalt');
		expect(note.about('Weihnachten')?.ready).toBe(false);
		note.meaningReady('Weihnachten');
		expect(note.about('Weihnachten')).toMatchObject({ pending: false, ready: true });
		note.withMeaning();
		expect(note.ratio('Weihnachten')).toBeUndefined();
		expect(note.about('Weihnachten')).toBeNull();
	});

	it('says why without promising the meaning, and nothing for a search with meaning', () => {
		const note = new SearchNote();
		const failed = { code: 'search_embed_failed', params: {} } as const;
		note.answered('Strom', { mode: 'words', reason: failed, meaning_pending: false });
		expect(note.about('Strom')).toMatchObject({ pending: false, ready: false });
		expect(note.ratio('Strom')).toBeUndefined();
		note.answered('Strom', { mode: 'hybrid', reason: null, meaning_pending: false });
		expect(note.about('Strom')).toBeNull();
	});

	it('stops promising the meaning after a while, and tells when an answer takes long', () => {
		const note = new SearchNote();
		note.answered('Weihnachten', { mode: 'words', reason: timeout, meaning_pending: true });
		vi.advanceTimersByTime(PENDING_FOR);
		expect(note.about('Weihnachten')?.pending).toBe(false);
		note.waiting(true);
		vi.advanceTimersByTime(SLOW_AFTER - 1);
		expect(note.slow).toBe(false);
		vi.advanceTimersByTime(1);
		expect(note.slow).toBe(true);
		note.waiting(false);
		expect(note.slow).toBe(false);
	});
});
