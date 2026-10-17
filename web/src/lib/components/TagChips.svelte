<script lang="ts">
	import TagChip from '#lib/components/TagChip.svelte';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { shownChips } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The shown tags of a document, each by its own name with the path as tooltip (and, where
	// `interactive`, on a tap). The groups of its contact and type stand next to them
	// (`NamesLine`, `GroupChips`).
	let {
		document,
		lookup,
		interactive = false,
		size = 'sm',
		class: className
	}: {
		document: { tag_ids: readonly string[] };
		lookup: Lookup | null;
		interactive?: boolean;
		size?: 'sm' | 'md';
		class?: string;
	} = $props();

	const tags = $derived(lookup ? shownChips(lookup.tags, document.tag_ids) : []);
</script>

{#if tags.length > 0}
	<span class={cn('flex min-w-0 flex-wrap gap-1', className)}>
		{#each tags as tag (tag.id)}<TagChip {tag} {interactive} {size} />{/each}
	</span>
{/if}
