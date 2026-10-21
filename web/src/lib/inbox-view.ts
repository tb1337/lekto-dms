/**
 * The inbox page: its tabs as they stand in the URL (`?tab=`).
 */
import type { components } from '#lib/api/schema.ts';
import { BASE } from '#lib/base.ts';

export type InboxTab = components['schemas']['InboxTab'];
export type InboxItem = components['schemas']['InboxItemOut'];

/** The tabs after "all" (everything open), in their order. */
export const INBOX_TABS: readonly InboxTab[] = ['new', 'review', 'intervene', 'processing', 'done'];

/** The tab a URL names; null for all that is open (none, or an unknown one). */
export function inboxTabOf(params: Pick<URLSearchParams, 'get'>): InboxTab | null {
	const tab = params.get('tab') ?? '';
	return (INBOX_TABS as readonly string[]).includes(tab) ? (tab as InboxTab) : null;
}

/** The address of a tab of the inbox; null: all that is open. */
export function inboxTabHref(tab: InboxTab | null): string {
	return tab ? `${BASE}/inbox?tab=${tab}` : `${BASE}/inbox`;
}
