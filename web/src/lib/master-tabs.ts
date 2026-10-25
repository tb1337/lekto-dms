/**
 * The master data page: its tabs as they stand in the URL (`?tab=`): contacts, document types,
 * every kind of tag, fields.
 */

/** The tabs in their order; the first is the one shown without a choice. */
export const MASTER_TABS = ['contacts', 'document-types', 'tags', 'fields'] as const;
export type MasterTab = (typeof MASTER_TABS)[number];

/** The tab a URL names; the first for none or an unknown one. */
export function masterTabOf(params: Pick<URLSearchParams, 'get'>): MasterTab {
	const tab = params.get('tab') ?? '';
	return (MASTER_TABS as readonly string[]).includes(tab) ? (tab as MasterTab) : MASTER_TABS[0];
}
