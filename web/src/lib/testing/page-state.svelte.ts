/**
 * A stand-in for SvelteKit's `page` from `$app/state` that pages react to, for tests that move
 * from one address to another: `vi.mock('$app/state', async () => ({ page: (await
 * import('#lib/testing/page-state.svelte.ts')).testPage }))`, then `goTo(…)`.
 */
export const testPage = $state<{
	url: URL;
	params: Record<string, string>;
	state: App.PageState;
}>({
	// Replaced as a whole, never changed in place (as SvelteKit's).
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	url: new URL('http://lekto/ui/inbox'),
	params: {},
	state: {}
});

/** Go to `href` (below `http://lekto`) with these route parameters and this history entry. */
export function goTo(
	href: string,
	params: Record<string, string> = {},
	state: App.PageState = {}
): void {
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	testPage.url = new URL(href, 'http://lekto');
	testPage.params = params;
	testPage.state = state;
}
