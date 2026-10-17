<script lang="ts">
	import GroupChips from '#lib/components/GroupChips.svelte';
	import type { Tag } from '#lib/masterdata.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// A document's contact and type by name, each with its shown groups (outlined chips), and a
	// date, apart by "·": a line of a card or a row, inside its link.
	let {
		parts,
		date = null,
		tags,
		class: className
	}: {
		parts: readonly { name: string | null | undefined; groupIds?: readonly string[] }[];
		date?: string | null;
		tags: readonly Tag[];
		class?: string;
	} = $props();
	const named = $derived(parts.filter((part) => part.name));
</script>

{#if named.length > 0 || date}
	<span class={cn('flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1', className)}>
		{#each named as part, index (index)}
			{#if index > 0}<span aria-hidden="true">·</span>{/if}
			<span class="min-w-0 truncate">{part.name}</span>
			<GroupChips {tags} ids={part.groupIds ?? []} interactive={false} />
		{/each}
		{#if date}
			{#if named.length > 0}<span aria-hidden="true">·</span>{/if}
			<span class="whitespace-nowrap">{date}</span>
		{/if}
	</span>
{/if}
