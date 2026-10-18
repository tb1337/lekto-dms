import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { scope } from '#lib/scope.svelte.ts';
import { session } from '#lib/session.svelte.ts';
import { summaryOf } from '#lib/testing/documents.ts';
import { badgeLabel, badgeText, badgeTone, inbox } from './inbox.svelte.ts';

const summary = summaryOf;

describe('inbox badge', () => {
	it.each([
		[{ intervene: 1, review: 2, new: 3 }, 'red'],
		[{ review: 1, new: 3, processing: 1 }, 'yellow'],
		[{ new: 2 }, 'green'],
		[{ processing: 2 }, 'grey']
	] as const)('takes the colour of the worst lane in %o', (counts, tone) => {
		expect(badgeTone(summary(counts))).toBe(tone);
	});

	it('shows nothing while nothing is open', () => {
		expect(badgeTone(summary({ done: 4 }))).toBeNull();
		expect(badgeTone(null)).toBeNull();
	});

	it('names what is in it', () => {
		expect(badgeLabel(summary({ intervene: 1, review: 2, new: 1, processing: 1 }))).toBe(
			[
				m.inbox_badge_total({ count: 5 }),
				m.inbox_badge_red({ count: 1 }),
				m.inbox_badge_yellow({ count: 2 }),
				m.inbox_badge_new({ count: 1 }),
				m.inbox_badge_processing({ count: 1 })
			].join(', ')
		);
		expect(badgeLabel(summary({ new: 3 }))).toBe(
			`${m.inbox_badge_total({ count: 3 })}, ${m.inbox_badge_new({ count: 3 })}`
		);
	});

	it('cuts a long number short', () => {
		expect(badgeText(7)).toBe('7');
		expect(badgeText(99)).toBe('99');
		expect(badgeText(1234)).toBe('99+');
	});
});

describe('inbox summary', () => {
	const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

	beforeEach(() => {
		session.start({
			user: { id: 'admin', username: 'admin', role: 'admin' },
			method: 'password',
			expires_at: '2026-10-18T12:00:00Z',
			csrf_token: 'token'
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(
			async () =>
				new Response(JSON.stringify(summary({ review: 1 })), {
					headers: { 'content-type': 'application/json' }
				})
		);
		vi.stubGlobal('fetch', fetchMock);
	});

	afterEach(() => {
		inbox.stop();
		scope.set(false);
		session.clear();
		vi.unstubAllGlobals();
	});

	it('is fetched for the scope chosen', async () => {
		scope.set(true);
		await inbox.refresh();
		const url = new URL(fetchMock.mock.calls[0][0].url);
		expect(url.pathname).toBe('/api/v1/inbox/summary');
		expect(url.searchParams.get('all_users')).toBe('true');
		expect(inbox.open).toBe(1);
		expect(inbox.summary?.worst_lane).toBe('yellow');
	});

	it('is fetched again when the window comes back into view', async () => {
		vi.useFakeTimers();
		try {
			inbox.start();
			await vi.runAllTimersAsync();
			const before = fetchMock.mock.calls.length;
			window.dispatchEvent(new Event('focus'));
			await vi.runAllTimersAsync();
			expect(fetchMock.mock.calls.length).toBe(before + 1);
		} finally {
			vi.useRealTimers();
		}
	});
});
