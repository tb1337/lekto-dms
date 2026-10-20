<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { NO_FILTERS, isFiltered, type Filters } from '#lib/filters.ts';
	import { spaceLabel, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { periodLabel } from '#lib/period-label.ts';
	import { session } from '#lib/session.svelte.ts';
	import { pathLabel } from '#lib/tags.ts';

	// What narrows the list, each as a chip that lets it go (a topic square, a group outlined),
	// and a reset; nothing while nothing is chosen.
	let {
		filters,
		lookup,
		onchange
	}: { filters: Filters; lookup: Lookup; onchange: (filters: Filters) => void } = $props();

	interface Chip {
		key: string;
		name: string;
		label: string;
		shape: 'round' | 'square' | 'outline';
		without: Partial<Filters>;
	}

	const chips = $derived.by(() => {
		const tags = new Map(lookup.tags.map((tag) => [tag.id, pathLabel(tag)]));
		const result: Chip[] = [];
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
				result.push({
					key: `${list.key}:${id}`,
					name,
					label: list.remove({ name }),
					shape: list.shape,
					without: { [list.key]: filters[list.key].filter((entry) => entry !== id) }
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
		return result;
	});
</script>

{#if isFiltered(filters)}
	<div class="flex flex-wrap items-center gap-2" role="group" aria-label={m.filters_active()}>
		{#each chips as chip (chip.key)}
			<span
				class={[
					'inline-flex h-8 max-w-full items-center gap-1 pr-1 pl-3 text-sm',
					chip.shape === 'square' ? 'rounded-md' : 'rounded-full',
					chip.shape === 'outline'
						? 'border bg-background'
						: 'border border-primary/40 bg-panel text-brand'
				]}
			>
				<span class="truncate">{chip.name}</span>
				<button
					type="button"
					class="grid size-6 shrink-0 place-items-center rounded-full hover:bg-background"
					aria-label={chip.label}
					onclick={() => onchange({ ...filters, ...chip.without })}
				>
					<X class="size-3.5" aria-hidden="true" />
				</button>
			</span>
		{/each}
		<Button variant="ghost" size="sm" onclick={() => onchange(NO_FILTERS)}>
			{m.filter_reset()}
		</Button>
	</div>
{/if}
