<script lang="ts">
	import { page } from '$app/state';
	import { BASE } from '#lib/base.ts';
	import BackLink from '#lib/components/BackLink.svelte';
	import { m } from '#lib/paraglide/messages.js';
	import { returnTo } from '#lib/return-to.svelte.ts';

	// The way back from a document: after a jump (the Beam, a dialog) to the place it came from,
	// one step back in the history (`lib/way-back.ts`); else to the inbox it was opened from, or
	// to the document list as it was left.
	let { inbox }: { inbox: boolean } = $props();

	const from = $derived(page.state.from ?? null);
</script>

{#if from}
	<BackLink
		href={inbox ? `${BASE}/inbox` : returnTo.documents}
		label={m.back_to({ place: from.label })}
		back={() => history.back()}
	/>
{:else}
	<BackLink
		href={inbox ? `${BASE}/inbox` : returnTo.documents}
		label={inbox ? m.nav_inbox() : m.nav_documents()}
		state={inbox ? undefined : returnTo.state}
	/>
{/if}
