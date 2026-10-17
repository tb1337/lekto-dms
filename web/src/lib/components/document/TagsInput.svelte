<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import TagChip from '#lib/components/TagChip.svelte';
	import { buttonVariants } from '#lib/components/ui/button/index.ts';
	import * as Command from '#lib/components/ui/command/index.ts';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import type { Tag } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { above, matchesQuery, normalise, ofScope, pathLabel } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The tags of a document: chips (the tag's own name, its path as tooltip and on a tap) to
	// remove, and a search to add a document tag, which finds a tag by the name of a tag above
	// it too. A tag added below one set replaces it, as the API keeps them; tags above one set
	// are not offered. `id` labels the button that adds.
	let {
		tags = $bindable(),
		all,
		id,
		disabled = false
	}: { tags: string[]; all: readonly Tag[]; id: string; disabled?: boolean } = $props();

	let open = $state(false);
	let query = $state('');
	const byId = $derived(new Map(all.map((tag) => [tag.id, tag])));
	// Neither the tags set nor those above them (the tag set says more).
	const free = $derived.by(() => {
		const higher = above(all, tags);
		return ofScope(all, 'document').filter((tag) => !tags.includes(tag.id) && !higher.has(tag.id));
	});
	const found = $derived(free.filter((tag) => matchesQuery(tag, query)));
	const addable = $derived(!disabled && free.length > 0);

	function chip(id: string): Pick<Tag, 'id' | 'name' | 'path'> {
		return byId.get(id) ?? { id, name: id, path: [id] };
	}

	function add(tag: string) {
		tags = normalise(all, [...tags, tag]);
		open = false;
		query = '';
	}
</script>

<!-- The chips carry `id` while there is no button to add one: the field's label points here. -->
{#if tags.length > 0 || !addable}
	<div
		id={addable ? undefined : id}
		role="group"
		aria-labelledby="{id}-label"
		class="flex flex-wrap gap-1.5"
	>
		{#each tags as tag (tag)}
			<TagChip
				tag={chip(tag)}
				interactive
				onremove={disabled ? undefined : () => (tags = tags.filter((entry) => entry !== tag))}
				removeLabel={m.filter_tag_remove({ name: pathLabel(chip(tag)) })}
			/>
		{/each}
	</div>
{/if}
{#if addable}
	<Popover.Root bind:open>
		<Popover.Trigger
			{id}
			class={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-fit')}
			aria-label={m.field_tag_add()}
		>
			<Plus aria-hidden="true" />
			{m.field_tag_add()}
		</Popover.Trigger>
		<Popover.Content class="w-72 p-0" align="start">
			<Command.Root shouldFilter={false}>
				<Command.Input
					bind:value={query}
					placeholder={m.assignment_search()}
					aria-label={m.assignment_search()}
				/>
				<Command.List>
					<Command.Empty class="py-4 text-center text-sm text-muted-foreground">
						{m.assignment_none_found()}
					</Command.Empty>
					{#each found as tag (tag.id)}
						<Command.Item
							value={tag.id}
							onSelect={() => add(tag.id)}
							class="flex-col items-start gap-0"
						>
							<span class="max-w-full truncate">{tag.name}</span>
							{#if tag.path.length > 1}
								<span class="max-w-full truncate text-xs text-muted-foreground">
									{pathLabel(tag)}
								</span>
							{/if}
						</Command.Item>
					{/each}
				</Command.List>
			</Command.Root>
		</Popover.Content>
	</Popover.Root>
{/if}
