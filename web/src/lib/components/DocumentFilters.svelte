<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import NativeSelect from '#lib/components/NativeSelect.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import {
		LANE_FILTERS,
		NO_FILTERS,
		isFiltered,
		type Filters,
		type LaneFilter
	} from '#lib/filters.ts';
	import { spaceLabel, type Lookup, type TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { pathLabel, tagOptions } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The filters of the list and the search. The page stores them in the URL.
	let {
		filters,
		lookup,
		onchange
	}: { filters: Filters; lookup: Lookup; onchange: (filters: Filters) => void } = $props();

	const laneLabel: Record<LaneFilter, () => string> = {
		green: m.lane_green,
		yellow: m.lane_yellow,
		red: m.lane_red,
		processing: m.lane_running
	};
	const all = (label: string, list: readonly { id: string; name: string }[]) => [
		{ value: '', label },
		...list.map((entry) => ({ value: entry.id, label: entry.name }))
	];
	const spaces = $derived(
		lookup.spaces.map((space) => ({
			id: space.id,
			name: spaceLabel(space, lookup.users, session.user?.id)
		}))
	);
	// Tags and groups by their path; each picked one stands as a chip.
	const tagName = $derived(new Map(lookup.tags.map((tag) => [tag.id, pathLabel(tag)])));
	const picks = $derived([
		{ key: 'tags' as const, scope: 'document' as const, label: m.filter_tag_add() },
		{
			key: 'contactGroups' as const,
			scope: 'contact' as const,
			label: m.filter_contact_group_add()
		},
		{
			key: 'typeGroups' as const,
			scope: 'document_type' as const,
			label: m.filter_type_group_add()
		}
	]);
	const chips = $derived(
		picks.flatMap(({ key }) =>
			filters[key].map((id) => ({
				key,
				id,
				name: tagName.get(id) ?? id,
				remove: key === 'tags' ? m.filter_tag_remove : m.filter_group_remove
			}))
		)
	);

	function free(key: 'tags' | 'contactGroups' | 'typeGroups', scope: TagScope) {
		return tagOptions(lookup.tags, scope).filter((option) => !filters[key].includes(option.value));
	}

	function set(patch: Partial<Filters>) {
		onchange({ ...filters, ...patch });
	}

	function toggleLane(lane: LaneFilter) {
		set({
			lanes: filters.lanes.includes(lane)
				? filters.lanes.filter((entry) => entry !== lane)
				: [...filters.lanes, lane]
		});
	}
</script>

<div class="flex flex-col gap-3">
	<div class="flex flex-wrap gap-3">
		<NativeSelect
			aria-label={m.filter_contact()}
			value={filters.contact ?? ''}
			options={all(m.filter_contact(), lookup.contacts)}
			onchange={(value) => set({ contact: value || null })}
			class="h-10 w-48"
		/>
		<NativeSelect
			aria-label={m.filter_type()}
			value={filters.type ?? ''}
			options={all(m.filter_type(), lookup.documentTypes)}
			onchange={(value) => set({ type: value || null })}
			class="h-10 w-48"
		/>
		<NativeSelect
			aria-label={m.filter_space()}
			value={filters.space ?? ''}
			options={all(m.filter_space(), spaces)}
			onchange={(value) => set({ space: value || null })}
			class="h-10 w-48"
		/>
		<NativeSelect
			aria-label={m.filter_field()}
			value={filters.field ?? ''}
			options={all(m.filter_field(), lookup.fields)}
			onchange={(value) => set({ field: value || null })}
			class="h-10 w-48"
		/>
		{#each picks as pick (pick.key)}
			{@const options = free(pick.key, pick.scope)}
			{#if options.length > 0 || filters[pick.key].length > 0}
				{#key filters[pick.key].length}
					<NativeSelect
						aria-label={pick.label}
						value=""
						options={[{ value: '', label: pick.label }, ...options]}
						onchange={(value) => value && set({ [pick.key]: [...filters[pick.key], value] })}
						class="h-10 w-48"
					/>
				{/key}
			{/if}
		{/each}
	</div>
	<div class="flex flex-wrap items-center gap-2">
		{#each LANE_FILTERS as lane (lane)}
			<button
				type="button"
				aria-pressed={filters.lanes.includes(lane)}
				onclick={() => toggleLane(lane)}
				class={cn(
					'h-8 rounded-full border px-3 text-sm transition-colors',
					filters.lanes.includes(lane)
						? 'border-primary bg-secondary font-medium'
						: 'text-muted-foreground hover:text-foreground'
				)}
			>
				{laneLabel[lane]()}
			</button>
		{/each}
		{#each chips as chip (`${chip.key}:${chip.id}`)}
			<span
				class="inline-flex h-8 max-w-full items-center gap-1 rounded-full bg-secondary pr-1 pl-3 text-sm"
			>
				<span class="truncate">{chip.name}</span>
				<button
					type="button"
					class="grid size-6 shrink-0 place-items-center rounded-full hover:bg-background"
					aria-label={chip.remove({ name: chip.name })}
					onclick={() =>
						set({ [chip.key]: filters[chip.key].filter((entry) => entry !== chip.id) })}
				>
					<X class="size-3.5" aria-hidden="true" />
				</button>
			</span>
		{/each}
		{#if isFiltered(filters)}
			<Button variant="ghost" size="sm" onclick={() => onchange(NO_FILTERS)}>
				{m.filter_reset()}
			</Button>
		{/if}
	</div>
</div>
