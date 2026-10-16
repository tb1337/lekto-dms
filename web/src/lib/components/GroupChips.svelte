<script lang="ts">
	import TagChip from '#lib/components/TagChip.svelte';
	import type { Tag } from '#lib/masterdata.svelte.ts';
	import { shownChips } from '#lib/tags.ts';

	// The shown groups of a contact or type (`ids`), outlined chips under its field; they come
	// with the contact or type and are not removed at the document.
	let { tags, ids }: { tags: readonly Tag[]; ids: readonly string[] } = $props();
	const groups = $derived(shownChips(tags, ids));
</script>

{#if groups.length > 0}
	<div class="mt-1.5 flex flex-wrap gap-1">
		{#each groups as tag (tag.id)}<TagChip {tag} group interactive size="sm" />{/each}
	</div>
{/if}
