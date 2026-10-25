/** The tabs of the page "System"; the first is shown without `?tab=` and for an unknown one. */
export const SYSTEM_TABS = ['automation', 'classifier', 'search', 'jobs'] as const;
export type SystemTab = (typeof SYSTEM_TABS)[number];

export function systemTab(params: Pick<URLSearchParams, 'get'>): SystemTab {
	const tab = params.get('tab') ?? '';
	return (SYSTEM_TABS as readonly string[]).includes(tab) ? (tab as SystemTab) : SYSTEM_TABS[0];
}
