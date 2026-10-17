<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import TagChip from '#lib/components/TagChip.svelte';
	import TagPickerDialog from '#lib/components/TagPickerDialog.svelte';
	import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { pathLabel } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The groups of a contact or a type, the topics of a contact: chips to remove and a button
	// that opens the picker over the editor (`TagPickerDialog`). A chosen tag missing from
	// `tags` (deleted meanwhile) stays as a chip until removed.
	let {
		id,
		label,
		title,
		scope,
		tags,
		selected,
		onchange
	}: {
		id: string;
		/** What the chips are ("Groups"). */
		label: string;
		/** The picker's title, the tags of the scope ("Contact groups"). */
		title: string;
		scope: TagScope;
		tags: readonly Tag[];
		selected: readonly string[];
		onchange: (selected: string[]) => void;
	} = $props();

	let open = $state(false);
	const byId = $derived(new Map(tags.map((tag) => [tag.id, tag])));
	const chips = $derived(
		[...new Set(selected)].map(
			(value) => byId.get(value) ?? { id: value, name: m.rule_unknown(), path: [m.rule_unknown()] }
		)
	);
	const isTopic = $derived(scope === 'topic');
</script>

<div
	{id}
	role="group"
	aria-label={label}
	class="flex min-w-0 flex-wrap items-center gap-2 rounded-xl border border-input bg-card p-2 dark:bg-input/30"
>
	{#each chips as tag (tag.id)}
		<TagChip
			{tag}
			group={!isTopic}
			topic={isTopic}
			interactive
			onremove={() => onchange(selected.filter((entry) => entry !== tag.id))}
			removeLabel={m.rule_remove_value({ name: pathLabel(tag) })}
		/>
	{/each}
	<button
		type="button"
		aria-haspopup="dialog"
		aria-label={isTopic ? m.picker_add_topic_label() : m.picker_add_group_label()}
		class={cn(
			'inline-flex h-8 items-center gap-1.5 border border-dashed border-muted-foreground/50 px-3 text-sm text-brand transition-colors hover:bg-secondary max-sm:h-10',
			isTopic ? 'rounded-md' : 'rounded-full'
		)}
		onclick={() => (open = true)}
	>
		<Plus class="size-4" aria-hidden="true" />
		{isTopic ? m.picker_add_topic() : m.picker_add_group()}
	</button>
</div>

<TagPickerDialog bind:open {title} {scope} {tags} {selected} {onchange} />
