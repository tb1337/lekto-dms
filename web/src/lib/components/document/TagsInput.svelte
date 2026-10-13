<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import NativeSelect from '#lib/components/NativeSelect.svelte';
	import type { MasterData } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The tags of a document: chips to remove, a select to add one (`id` labels it).
	let {
		tags = $bindable(),
		all,
		id,
		disabled = false
	}: { tags: string[]; all: readonly MasterData[]; id: string; disabled?: boolean } = $props();

	const name = $derived(new Map(all.map((tag) => [tag.id, tag.name])));
	const free = $derived(all.filter((tag) => !tags.includes(tag.id)));
</script>

{#if tags.length > 0}
	<div class="flex flex-wrap gap-1.5">
		{#each tags as tag (tag)}
			<span class="inline-flex h-8 items-center gap-1 rounded-full bg-secondary pr-1 pl-3 text-sm">
				{name.get(tag) ?? tag}
				{#if !disabled}
					<button
						type="button"
						class="grid size-6 place-items-center rounded-full hover:bg-background"
						aria-label={m.filter_tag_remove({ name: name.get(tag) ?? tag })}
						onclick={() => (tags = tags.filter((entry) => entry !== tag))}
					>
						<X class="size-3.5" aria-hidden="true" />
					</button>
				{/if}
			</span>
		{/each}
	</div>
{/if}
{#if !disabled}
	{#key tags.length}
		<NativeSelect
			{id}
			value=""
			options={[
				{ value: '', label: m.field_tag_add() },
				...free.map((tag) => ({ value: tag.id, label: tag.name }))
			]}
			onchange={(picked) => picked && (tags = [...tags, picked])}
		/>
	{/key}
{/if}
