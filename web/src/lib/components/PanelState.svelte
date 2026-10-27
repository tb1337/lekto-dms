<script lang="ts">
	import type { Snippet } from 'svelte';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Loading from '#lib/components/Loading.svelte';

	// What a panel of the master data shows in place of its list: the problem of its load (with
	// a way to try again), that it is loading, or that there is nothing to list (`empty`, the
	// words for it); else the list, `children`.
	let {
		problem,
		loading,
		empty,
		onretry,
		children
	}: {
		problem: string | null;
		loading: boolean;
		empty: string | null;
		onretry: () => void;
		children: Snippet;
	} = $props();
</script>

{#if problem}
	<LoadProblem {problem} {onretry} />
{:else if loading}
	<Loading />
{:else if empty !== null}
	<EmptyNote compact>{empty}</EmptyNote>
{:else}
	{@render children()}
{/if}
