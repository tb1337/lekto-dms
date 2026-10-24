/**
 * What the inbox holds (`GET /inbox/summary`): the counter at the menu entry, coloured by the
 * worst lane among the open documents, and the counts of the inbox's tabs. Fetched again after
 * events and when the window comes back into view (seen in another tab or on another device
 * sends no event).
 */
import { api } from '#lib/api/client.ts';
import type { components } from '#lib/api/schema.ts';
import { events, NODE_EVENTS } from '#lib/events.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { scope } from '#lib/scope.svelte.ts';

export type InboxSummary = components['schemas']['InboxSummaryOut'];
export type BadgeTone = 'red' | 'yellow' | 'green' | 'grey';

/** The counter's colours: the lane's ground and its writing (4.5:1 in light and dark). */
export const BADGE_TONES: Record<BadgeTone, string> = {
	red: 'border-lane-red-foreground/25 bg-lane-red text-lane-red-foreground',
	yellow: 'border-lane-yellow-foreground/25 bg-lane-yellow text-lane-yellow-foreground',
	green: 'border-lane-green-foreground/25 bg-lane-green text-lane-green-foreground',
	grey: 'border-lane-running-foreground/25 bg-lane-running text-lane-running-foreground'
};

/** The counter's colour: the worst lane among the open documents; grey with only documents
 * in processing. None with nothing open. */
export function badgeTone(summary: InboxSummary | null): BadgeTone | null {
	if (!summary || summary.open === 0) return null;
	return summary.worst_lane ?? 'grey';
}

/** What a screen reader says of the counter: everything open, then each kind in it. */
export function badgeLabel(summary: InboxSummary): string {
	const parts = [
		m.inbox_badge_total({ count: summary.open }),
		summary.intervene > 0 && m.inbox_badge_red({ count: summary.intervene }),
		summary.review > 0 && m.inbox_badge_yellow({ count: summary.review }),
		summary.new > 0 && m.inbox_badge_new({ count: summary.new }),
		summary.processing > 0 && m.inbox_badge_processing({ count: summary.processing })
	];
	return parts.filter(Boolean).join(', ');
}

/** The counter's number; more than two digits are cut short (the label has the count). */
export function badgeText(open: number): string {
	return open > 99 ? '99+' : String(open);
}

class Inbox {
	summary = $state<InboxSummary | null>(null);
	#timer: ReturnType<typeof setTimeout> | undefined;
	#stop: (() => void) | null = null;
	// An answer overtaken by a later request (the scope changed meanwhile) is dropped.
	#request = 0;

	/** Everything open: the counter's number. */
	get open(): number {
		return this.summary?.open ?? 0;
	}

	/** Fetch the summary again; while the server cannot be reached the last one stays. */
	async refresh(): Promise<void> {
		const request = ++this.#request;
		try {
			const { data } = await api.GET('/api/v1/inbox/summary', {
				params: { query: { all_users: scope.query } }
			});
			if (data && request === this.#request) this.summary = data;
		} catch {
			// Offline (fetch rejects): the counter keeps what it showed until the next refresh.
		}
	}

	#later(wait = 500): void {
		clearTimeout(this.#timer);
		this.#timer = setTimeout(() => void this.refresh(), wait);
	}

	/** Follow the event stream and the window while someone is signed in. */
	start(): void {
		if (this.#stop) return;
		void this.refresh();
		const stopEvents = events.subscribe((event) => {
			if (!NODE_EVENTS.has(event.type)) this.#later();
		});
		const visible = () => {
			if (document.visibilityState === 'visible') this.#later(0);
		};
		window.addEventListener('focus', visible);
		document.addEventListener('visibilitychange', visible);
		this.#stop = () => {
			clearTimeout(this.#timer);
			stopEvents();
			window.removeEventListener('focus', visible);
			document.removeEventListener('visibilitychange', visible);
		};
	}

	stop(): void {
		this.#stop?.();
		this.#stop = null;
		this.#request++;
		this.summary = null;
	}
}

export const inbox = new Inbox();
