<script lang="ts">
	import type { Snippet } from 'svelte';
	import SearchField from '#lib/components/SearchField.svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { toggled } from '#lib/picking.ts';
	import { matchesQuery, ofScope, pathLabel } from '#lib/tags.ts';
	import { ChoiceBox } from '#lib/components/ui/choice/index.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import Eyebrow from '#lib/components/page/Eyebrow.svelte';

	// Several tags of one scope to choose: a search over their paths, then every tag of the scope
	// that may be chosen (`offered`) with a checkbox, nested as in its tree; while searching the
	// matches with their paths, or all of them when none matches. `actions` stand between the
	// search and the list (the offers to create a tag, which need the query). In a dialog or a
	// popover (`TagPicker`).
	let {
		title,
		scope,
		tags,
		selected,
		onchange,
		query = $bindable(''),
		searchLabel = m.assignment_search(),
		offered = () => true,
		search = $bindable(null),
		actions
	}: {
		/** The tags of the scope ("Contact groups"), for "all …" when nothing matches. */
		title: string;
		scope: TagScope;
		tags: readonly Tag[];
		selected: readonly string[];
		onchange: (selected: string[]) => void;
		query?: string;
		searchLabel?: string;
		/** Whether a tag may be chosen (a chosen one always shows). */
		offered?: (tag: Tag) => boolean;
		/** The search field, for the focus. */
		search?: HTMLInputElement | null;
		actions?: Snippet;
	} = $props();

	const own = $derived(
		ofScope(tags, scope).filter((tag) => selected.includes(tag.id) || offered(tag))
	);
	const searching = $derived(query.trim() !== '');
	const matches = $derived(searching ? own.filter((tag) => matchesQuery(tag, query)) : own);
	// Nothing found: all of them, to choose from anyway.
	const listed = $derived(searching && matches.length === 0 ? own : matches);
	const isGroup = $derived(scope === 'contact' || scope === 'document_type');

	function toggle(id: string, on: boolean) {
		onchange(toggled(selected, id, on));
	}
</script>

<div class="shrink-0 px-4 pb-3">
	<SearchField bind:ref={search} bind:value={query} label={searchLabel} />
</div>
<div class="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overscroll-contain px-4 pb-4">
	{@render actions?.()}
	{#if searching && matches.length === 0}
		<p class="px-1 text-sm text-muted-foreground">{m.picker_no_match()}</p>
		<Eyebrow as="h3" class="mt-2 px-1">
			{m.picker_all({ kind: title })}
		</Eyebrow>
	{/if}
	{#if listed.length > 0}
		<Card.Root as="ul" size="flush" class="divide-y overflow-hidden">
			{#each listed as tag (tag.id)}
				{@const nested = !searching || matches.length === 0}
				<li>
					<label
						class="flex min-h-12 cursor-pointer items-center gap-3 py-1.5 pr-3.5 pl-[calc(0.875rem+var(--depth)*1.5rem)] hover:bg-secondary/60"
						style="--depth: {nested ? tag.path.length - 1 : 0}"
					>
						<span class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-0.5">
							<TagChip
								tag={{ ...tag, path: [tag.name] }}
								group={isGroup}
								topic={scope === 'topic'}
							/>
							{#if !nested && tag.path.length > 1}
								<span class="text-xs text-muted-foreground">{pathLabel(tag)}</span>
							{/if}
						</span>
						<ChoiceBox
							aria-label={pathLabel(tag)}
							checked={selected.includes(tag.id)}
							onchange={(event) => toggle(tag.id, event.currentTarget.checked)}
						/>
					</label>
				</li>
			{/each}
		</Card.Root>
	{/if}
</div>
