<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { factFilterLabel } from '#lib/facts.ts';
	import { NO_FILTERS, isFiltered, type Filters } from '#lib/filters.ts';
	import TagChip from '#lib/components/TagChip.svelte';
	import { spaceLabel, type Lookup, type Tag } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { periodLabel } from '#lib/period-label.ts';
	import { session } from '#lib/session.svelte.ts';
	import { pathLabel } from '#lib/tags.ts';
	import Chip from '#lib/components/Chip.svelte';

	// What narrows the list, each as a chip that lets it go, and a reset; nothing while nothing
	// is chosen. Tags, topics and groups are their chips as everywhere (`TagChip`: colour and
	// icon, a topic square, a group outlined); the rest is brand-coloured. `readonly`: the chips
	// only (what a lens keeps). The words of a search (`query`) stand first, `onclearquery` ends
	// the search.
	let {
		filters,
		lookup,
		onchange,
		query = '',
		onclearquery,
		readonly = false
	}: {
		filters: Filters;
		lookup: Lookup;
		onchange?: (filters: Filters) => void;
		query?: string;
		onclearquery?: () => void;
		readonly?: boolean;
	} = $props();

	interface FilterChip {
		key: string;
		name: string;
		label: string;
		shape: 'round' | 'square' | 'outline';
		without: Partial<Filters>;
		/** A tag, topic or group: drawn as its chip. */
		tag?: Tag;
	}

	const chips = $derived.by(() => {
		const byId = new Map(lookup.tags.map((tag) => [tag.id, tag]));
		const tags = new Map(lookup.tags.map((tag) => [tag.id, pathLabel(tag)]));
		const result: FilterChip[] = [];
		const period = periodLabel(filters);
		if (period) {
			result.push({
				key: 'period',
				name: period,
				label: m.filter_remove({ name: period }),
				shape: 'round',
				without: { dateFrom: null, dateTo: null }
			});
		}
		const lists = [
			{
				key: 'contacts',
				named: (id: string) => lookup.contacts.find((entry) => entry.id === id)?.name,
				remove: m.filter_remove,
				shape: 'round'
			},
			{
				key: 'types',
				named: (id: string) => lookup.documentTypes.find((entry) => entry.id === id)?.name,
				remove: m.filter_remove,
				shape: 'round'
			},
			{
				key: 'topics',
				named: (id: string) => tags.get(id),
				remove: m.filter_topic_remove,
				shape: 'square'
			},
			{
				key: 'tags',
				named: (id: string) => tags.get(id),
				remove: m.filter_tag_remove,
				shape: 'round'
			},
			{
				key: 'contactGroups',
				named: (id: string) => tags.get(id),
				remove: m.filter_group_remove,
				shape: 'outline'
			},
			{
				key: 'typeGroups',
				named: (id: string) => tags.get(id),
				remove: m.filter_group_remove,
				shape: 'outline'
			},
			{
				key: 'spaces',
				named: (id: string) => {
					const space = lookup.spaces.find((entry) => entry.id === id);
					return space ? spaceLabel(space, lookup.users, session.user?.id) : undefined;
				},
				remove: m.filter_remove,
				shape: 'round'
			}
		] as const;
		for (const list of lists) {
			for (const id of filters[list.key]) {
				const name = list.named(id) ?? id;
				const tagged = ['topics', 'tags', 'contactGroups', 'typeGroups'].includes(list.key);
				result.push({
					key: `${list.key}:${id}`,
					name,
					label: list.remove({ name }),
					shape: list.shape,
					without: { [list.key]: filters[list.key].filter((entry) => entry !== id) },
					tag: tagged ? byId.get(id) : undefined
				});
			}
		}
		if (filters.field) {
			const field = lookup.fields.find((entry) => entry.id === filters.field)?.name;
			const name = `${m.filter_field()}: ${field ?? filters.field}`;
			result.push({
				key: 'field',
				name,
				label: m.filter_remove({ name }),
				shape: 'round',
				without: { field: null }
			});
		}
		for (const fact of filters.facts) {
			const name = `${m.filter_fact()}: ${factFilterLabel(fact)}`;
			result.push({
				key: `fact:${fact}`,
				name,
				label: m.filter_remove({ name }),
				shape: 'round',
				without: { facts: filters.facts.filter((entry) => entry !== fact) }
			});
		}
		return result;
	});
</script>

{#if isFiltered(filters) || query}
	<div class="flex flex-wrap items-center gap-2" role="group" aria-label={m.filters_active()}>
		{#if query}
			<Chip
				variant="outline"
				onremove={onclearquery}
				removeLabel={m.search_chip_remove({ words: query })}
			>
				{#snippet icon()}
					<SearchIcon class="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
				{/snippet}
				{m.search_chip({ words: query })}
			</Chip>
		{/if}
		{#each chips as chip (chip.key)}
			{#if chip.tag}
				<TagChip
					tag={chip.tag}
					group={chip.shape === 'outline'}
					topic={chip.shape === 'square'}
					onremove={readonly ? undefined : () => onchange?.({ ...filters, ...chip.without })}
					removeLabel={chip.label}
				/>
			{:else}
				<Chip
					variant={chip.shape === 'outline' ? 'outline' : 'selected'}
					onremove={readonly ? undefined : () => onchange?.({ ...filters, ...chip.without })}
					removeLabel={chip.label}>{chip.name}</Chip
				>
			{/if}
		{/each}
		{#if !readonly && isFiltered(filters)}
			<Button variant="ghost" size="sm" onclick={() => onchange?.(NO_FILTERS)}>
				{m.filter_reset()}
			</Button>
		{/if}
	</div>
{/if}
