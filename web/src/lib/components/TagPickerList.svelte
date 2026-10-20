<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import type { Snippet } from 'svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { matchesQuery, ofScope, pathLabel } from '#lib/tags.ts';

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
		onchange(on ? [...selected, id] : selected.filter((entry) => entry !== id));
	}
</script>

<div class="shrink-0 px-4 pb-3">
	<label
		class="flex h-11 items-center gap-2 rounded-xl bg-muted px-3 text-muted-foreground focus-within:ring-2 focus-within:ring-ring/40"
	>
		<SearchIcon class="size-4 shrink-0" aria-hidden="true" />
		<input
			bind:this={search}
			bind:value={query}
			type="search"
			aria-label={searchLabel}
			placeholder={searchLabel}
			class="h-full min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm"
		/>
	</label>
</div>
<div class="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overscroll-contain px-4 pb-4">
	{@render actions?.()}
	{#if searching && matches.length === 0}
		<p class="px-1 text-sm text-muted-foreground">{m.picker_no_match()}</p>
		<h3 class="mt-2 px-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
			{m.picker_all({ kind: title })}
		</h3>
	{/if}
	{#if listed.length > 0}
		<ul class="divide-y overflow-hidden rounded-2xl border bg-card">
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
						<input
							type="checkbox"
							class="size-5 shrink-0 accent-primary"
							aria-label={pathLabel(tag)}
							checked={selected.includes(tag.id)}
							onchange={(event) => toggle(tag.id, event.currentTarget.checked)}
						/>
					</label>
				</li>
			{/each}
		</ul>
	{/if}
</div>
