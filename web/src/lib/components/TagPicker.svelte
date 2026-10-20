<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import CreateOffer from '#lib/components/CreateOffer.svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import TagPickerDialog from '#lib/components/TagPickerDialog.svelte';
	import TagPickerList from '#lib/components/TagPickerList.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { creatable, createWithDetails } from '#lib/tag-create.ts';
	import { pathLabel } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The one field for tags: a document's tags, a contact's or a type's groups, a contact's
	// topics. Their chips to remove and a dashed button that opens the choice (`TagPickerList`):
	// wider than a phone in a popover at the button, on a phone a sheet from the bottom
	// (`TagPickerDialog`; Tobi, 20.10.2026). A chosen tag missing from `tags` (deleted meanwhile)
	// stays as a chip until removed. An admin's search that finds no tag named so offers to
	// create one in the tag dialog (`tag-create.ts`), chosen when made; `oncreated` tells the
	// editor. `offered`
	// narrows what may be chosen (a document: no tag above one set).
	let {
		id,
		label,
		labelledby,
		title,
		scope,
		tags,
		selected,
		onchange,
		offered,
		disabled = false,
		oncreated = () => {}
	}: {
		id: string;
		/** What the chips are ("Groups"). */
		label: string;
		/** The id of a visible label of the chips, named so instead of by `label`. */
		labelledby?: string;
		/** The choice's title, the tags of the scope ("Contact groups"). */
		title: string;
		scope: TagScope;
		tags: readonly Tag[];
		selected: readonly string[];
		onchange: (selected: string[]) => void;
		offered?: (tag: Tag) => boolean;
		/** Chips only: nothing to add or remove. */
		disabled?: boolean;
		oncreated?: (tag: Tag) => void;
	} = $props();

	let open = $state(false);
	let query = $state('');
	let search = $state<HTMLInputElement | null>(null);
	// Tags made here, until `tags` holds them too.
	let made = $state<Tag[]>([]);
	const known = $derived([
		...tags,
		...made.filter((tag) => !tags.some((other) => other.id === tag.id))
	]);
	const canCreate = $derived(session.isAdmin && creatable(known, scope, query));
	const byId = $derived(new Map(known.map((tag) => [tag.id, tag])));
	const chips = $derived(
		[...new Set(selected)].map(
			(value) => byId.get(value) ?? { id: value, name: m.rule_unknown(), path: [m.rule_unknown()] }
		)
	);
	const isTopic = $derived(scope === 'topic');
	const isGroup = $derived(scope === 'contact' || scope === 'document_type');
	const addText = $derived(
		isTopic ? m.picker_add_topic() : isGroup ? m.picker_add_group() : m.picker_add_tag()
	);
	const addLabel = $derived(
		isTopic ? m.picker_add_topic_label() : isGroup ? m.picker_add_group_label() : m.field_tag_add()
	);
	const searchLabel = $derived(session.isAdmin ? m.picker_search_create() : m.assignment_search());

	// The choice gives way to the tag dialog; the tag it makes is chosen.
	async function create() {
		const name = query;
		query = '';
		open = false;
		const tag = await createWithDetails(scope, name);
		if (!tag) return;
		made = [...made, tag];
		oncreated(tag);
		onchange([...selected, tag.id]);
	}
</script>

{#snippet offers()}
	{#if canCreate}
		<CreateOffer name={query.trim()} onclick={create} />
	{/if}
{/snippet}

{#snippet add(props: Record<string, unknown> = {})}
	<button
		type="button"
		{...props}
		aria-label={addLabel}
		class={cn(
			'inline-flex h-8 items-center gap-1.5 border border-dashed border-muted-foreground/50 px-3 text-sm text-brand transition-colors hover:bg-secondary max-sm:h-11',
			isTopic ? 'rounded-md' : 'rounded-full'
		)}
		onclick={() => {
			query = '';
			open = true;
		}}
	>
		<Plus class="size-4" aria-hidden="true" />
		{addText}
	</button>
{/snippet}

<div
	{id}
	role="group"
	aria-label={labelledby ? undefined : label}
	aria-labelledby={labelledby}
	class="flex min-w-0 flex-wrap items-center gap-2 rounded-xl border border-input bg-card p-2 dark:bg-input/30"
>
	{#each chips as tag (tag.id)}
		<TagChip
			{tag}
			group={isGroup}
			topic={isTopic}
			interactive
			onremove={disabled ? undefined : () => onchange(selected.filter((entry) => entry !== tag.id))}
			removeLabel={m.rule_remove_value({ name: pathLabel(tag) })}
		/>
	{/each}
	{#if !disabled}
		{#if phone.current}
			{@render add({ 'aria-haspopup': 'dialog', 'aria-expanded': open })}
		{:else}
			<Popover.Root bind:open onOpenChange={(next) => next || (query = '')}>
				<Popover.Trigger>
					{#snippet child({ props })}
						{@render add(props)}
					{/snippet}
				</Popover.Trigger>
				<Popover.Content
					align="start"
					collisionPadding={8}
					role="dialog"
					aria-labelledby="{id}-picker-title"
					class="flex max-h-[min(30rem,var(--bits-popover-content-available-height))] w-80 flex-col gap-0 p-0"
					onOpenAutoFocus={(event) => {
						event.preventDefault();
						search?.focus();
					}}
				>
					<div class="flex shrink-0 items-center justify-between gap-2 py-1.5 pr-1.5 pl-4">
						<span id="{id}-picker-title" class="text-sm font-semibold">{title}</span>
						<Button
							variant="ghost"
							size="sm"
							class="text-brand"
							onclick={() => {
								query = '';
								open = false;
							}}
						>
							{m.picker_done()}
						</Button>
					</div>
					<TagPickerList
						{title}
						{scope}
						tags={known}
						{selected}
						{onchange}
						{offered}
						{searchLabel}
						bind:query
						bind:search
						actions={offers}
					/>
				</Popover.Content>
			</Popover.Root>
		{/if}
	{/if}
</div>

{#if phone.current && !disabled}
	<TagPickerDialog
		bind:open
		bind:query
		{title}
		{scope}
		tags={known}
		{selected}
		{onchange}
		{offered}
		{searchLabel}
		actions={offers}
	/>
{/if}
