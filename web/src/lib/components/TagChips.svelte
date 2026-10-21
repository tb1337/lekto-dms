<script lang="ts">
	import TagChip from '#lib/components/TagChip.svelte';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { shownChips } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The shown topic and tags of a document, each by its own name with the path as tooltip
	// (and, where `interactive`, on a tap): the topic square and first, the tags round. The
	// groups of its contact and type stand next to them (`NamesLine`, `GroupChips`).
	let {
		document,
		lookup,
		interactive = false,
		size = 'sm',
		onImage = false,
		class: className
	}: {
		document: { tag_ids: readonly string[]; topic_id?: string | null };
		lookup: Lookup | null;
		interactive?: boolean;
		size?: 'sm' | 'md';
		/** On a document's image (a card): as glass with an edge. */
		onImage?: boolean;
		class?: string;
	} = $props();

	const tags = $derived(lookup ? shownChips(lookup.tags, document.tag_ids) : []);
	const topics = $derived(
		lookup && document.topic_id ? shownChips(lookup.tags, [document.topic_id]) : []
	);
</script>

{#if tags.length > 0 || topics.length > 0}
	<span class={cn('flex min-w-0 flex-wrap gap-1', className)}>
		{#each topics as tag (tag.id)}<TagChip {tag} topic {interactive} {size} {onImage} />{/each}
		{#each tags as tag (tag.id)}<TagChip {tag} {interactive} {size} {onImage} />{/each}
	</span>
{/if}
