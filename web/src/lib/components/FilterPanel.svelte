<script lang="ts">
	import { untrack } from 'svelte';
	import type { components } from '#lib/api/schema.ts';
	import FacetChips, { type ChipItem } from '#lib/components/FacetChips.svelte';
	import FacetList, { type FacetItem } from '#lib/components/FacetList.svelte';
	import FactFilter from '#lib/components/FactFilter.svelte';
	import FilterSection from '#lib/components/FilterSection.svelte';
	import Select from '#lib/components/Select.svelte';
	import PeriodFacet from '#lib/components/PeriodFacet.svelte';
	import { factFilterLabel } from '#lib/facts.ts';
	import type { Filters } from '#lib/filters.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { spaceLabel, type Lookup, type TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { periodLabel } from '#lib/period-label.ts';
	import { session } from '#lib/session.svelte.ts';
	import { below, ofScope, pathLabel } from '#lib/tags.ts';

	type Facets = components['schemas']['DocumentFacetsOut'];
	type ValueCount = components['schemas']['ValueCount'];

	// The filters of the document view, beside the list (or in a sheet on a phone), compact
	// however much there is: the period as tiles of years and bars of months; the contact by its
	// groups first (a bank, an insurer: which one matters less), then the most frequent contacts
	// of the chosen groups, a search and a picker of all; the type the same way; topics and tags
	// as their chips. Counts (`facets`) say how many documents each holds, most first; none while
	// searching (`showCounts`). Within a kind one of the chosen must match; tags all of them.
	let {
		filters,
		lookup,
		facets,
		showCounts,
		onchange
	}: {
		filters: Filters;
		lookup: Lookup;
		facets: Facets | null;
		showCounts: boolean;
		onchange: (filters: Filters) => void;
	} = $props();

	// Counts only where they are known: not while searching, not without facets.
	const counting = $derived(showCounts && facets !== null);

	function set(patch: Partial<Filters>) {
		onchange({ ...filters, ...patch });
	}

	function counts(list: readonly ValueCount[] | undefined): Map<string, number> {
		return new Map((list ?? []).flatMap((entry) => (entry.id ? [[entry.id, entry.count]] : [])));
	}
	const byCount = <T extends { count: number | null; label: string }>(a: T, b: T) =>
		(b.count ?? 0) - (a.count ?? 0) || a.label.localeCompare(b.label);

	const tagById = $derived(new Map(lookup.tags.map((tag) => [tag.id, tag])));

	/** The tags of `scope` as their chips (colour, icon): those with documents (or chosen), most
	 * first. */
	function chips(
		scope: TagScope,
		counted: Map<string, number>,
		chosen: readonly string[]
	): ChipItem[] {
		return ofScope(lookup.tags, scope)
			.filter((tag) => facets === null || counted.has(tag.id) || chosen.includes(tag.id))
			.map((tag) => ({
				id: tag.id,
				label: tag.name,
				title: pathLabel(tag),
				count: counting ? (counted.get(tag.id) ?? 0) : null,
				color: tag.color,
				icon: tag.icon
			}))
			.toSorted((a, b) => (counting ? byCount(a, b) : 0));
	}

	function groupNames(ids: readonly string[]): string {
		return ids.map((id) => tagById.get(id)?.name ?? id).join(', ');
	}

	function values(
		entries: readonly { id: string; name: string; group_ids: string[]; icon?: string | null }[],
		counted: Map<string, number>,
		groups: readonly string[]
	): { all: FacetItem[]; top: FacetItem[] } {
		const within =
			groups.length > 0 ? new Set(groups.flatMap((id) => [id, ...below(lookup.tags, id)])) : null;
		const all = entries
			.filter((entry) => within === null || entry.group_ids.some((id) => within.has(id)))
			.map((entry) => ({
				id: entry.id,
				label: entry.name,
				count: counting ? (counted.get(entry.id) ?? 0) : null,
				icon: entry.icon ?? null,
				hint: groupNames(entry.group_ids)
			}));
		const top = all.filter((item) => counted.has(item.id)).toSorted(byCount);
		return { all, top };
	}

	function chosenSummary(names: readonly string[]): string | null {
		if (names.length === 0) return null;
		return names.length === 1 ? names[0] : m.facet_chosen({ count: formatNumber(names.length) });
	}

	const contactGroups = $derived(
		chips('contact', counts(facets?.contact_groups), filters.contactGroups)
	);
	const typeGroups = $derived(
		chips('document_type', counts(facets?.document_type_groups), filters.typeGroups)
	);
	const topics = $derived(chips('topic', counts(facets?.topics), filters.topics));
	const tags = $derived(chips('document', counts(facets?.tags), filters.tags));
	const contacts = $derived(
		values(lookup.contacts, counts(facets?.contacts), filters.contactGroups)
	);
	const types = $derived(
		values(lookup.documentTypes, counts(facets?.document_types), filters.typeGroups)
	);
	const spaces = $derived(
		lookup.spaces.map((space) => ({
			id: space.id,
			label: spaceLabel(space, lookup.users, session.user?.id),
			count: null
		}))
	);
	const fields = $derived([
		{ value: '', label: m.filter_field() },
		...lookup.fields.map((field) => ({ value: field.id, label: field.name }))
	]);

	const contactSummary = $derived(
		chosenSummary([
			...filters.contactGroups.map((id) => tagById.get(id)?.name ?? id),
			...filters.contacts.map((id) => lookup.contacts.find((entry) => entry.id === id)?.name ?? id)
		])
	);
	const typeSummary = $derived(
		chosenSummary([
			...filters.typeGroups.map((id) => tagById.get(id)?.name ?? id),
			...filters.types.map(
				(id) => lookup.documentTypes.find((entry) => entry.id === id)?.name ?? id
			)
		])
	);

	// Open at first: what is used most, and what has a choice.
	const initial = untrack(() => filters);
	let periodOpen = $state(true);
	let contactOpen = $state(true);
	let typeOpen = $state(initial.types.length > 0 || initial.typeGroups.length > 0);
	let topicOpen = $state(initial.topics.length > 0);
	let tagsOpen = $state(true);
	let furtherOpen = $state(initial.spaces.length > 0 || initial.field !== null);
	let factsOpen = $state(initial.facts.length > 0);
</script>

<div class="flex flex-col gap-2">
	<FilterSection title={m.facet_period()} summary={periodLabel(filters)} bind:open={periodOpen}>
		<PeriodFacet
			years={facets?.years ?? []}
			undated={facets?.undated ?? 0}
			period={filters}
			showCounts={counting}
			onchange={(period) => set(period)}
		/>
	</FilterSection>

	{#if contactGroups.length > 0 || contacts.all.length > 0}
		<FilterSection title={m.facet_contact()} summary={contactSummary} bind:open={contactOpen}>
			<FacetChips
				look="group"
				label={m.facet_contact_groups()}
				items={contactGroups}
				selected={filters.contactGroups}
				onchange={(next) => set({ contactGroups: next })}
			/>
			<FacetList
				heading={filters.contactGroups.length > 0
					? m.facet_contacts_in({ groups: groupNames(filters.contactGroups) })
					: m.facet_top_contacts()}
				top={contacts.top}
				items={contacts.all}
				selected={filters.contacts}
				onchange={(next) => set({ contacts: next })}
				searchLabel={m.facet_search_contacts()}
				allLabel={m.facet_all_contacts({ count: formatNumber(contacts.all.length) })}
				pickerTitle={m.facet_contacts()}
			/>
		</FilterSection>
	{/if}

	{#if typeGroups.length > 0 || types.all.length > 0}
		<FilterSection title={m.facet_type()} summary={typeSummary} bind:open={typeOpen}>
			<FacetChips
				look="group"
				label={m.facet_type_groups()}
				items={typeGroups}
				selected={filters.typeGroups}
				onchange={(next) => set({ typeGroups: next })}
			/>
			<FacetList
				heading={filters.typeGroups.length > 0
					? m.facet_types_in({ groups: groupNames(filters.typeGroups) })
					: m.facet_top_types()}
				top={types.top}
				items={types.all}
				selected={filters.types}
				onchange={(next) => set({ types: next })}
				searchLabel={m.facet_search_types()}
				allLabel={m.facet_all_types({ count: formatNumber(types.all.length) })}
				pickerTitle={m.facet_types()}
			/>
		</FilterSection>
	{/if}

	{#if topics.length > 0}
		<FilterSection
			title={m.facet_topic()}
			summary={chosenSummary(filters.topics.map((id) => tagById.get(id)?.name ?? id))}
			bind:open={topicOpen}
		>
			<FacetChips
				look="topic"
				label={m.facet_topics()}
				items={topics}
				selected={filters.topics}
				onchange={(next) => set({ topics: next })}
			/>
		</FilterSection>
	{/if}

	{#if tags.length > 0}
		<FilterSection
			title={m.facet_tags()}
			summary={chosenSummary(filters.tags.map((id) => tagById.get(id)?.name ?? id))}
			bind:open={tagsOpen}
		>
			<FacetChips
				look="tag"
				label={m.facet_tags()}
				items={tags}
				selected={filters.tags}
				onchange={(next) => set({ tags: next })}
				limit={12}
				more={(count) => m.facet_all_tags({ count: formatNumber(count) })}
			/>
		</FilterSection>
	{/if}

	{#if spaces.length > 1 || lookup.fields.length > 0}
		<FilterSection
			title={m.facet_further()}
			summary={chosenSummary([
				...filters.spaces.map((id) => spaces.find((space) => space.id === id)?.label ?? id),
				...(filters.field ? [lookup.fields.find((f) => f.id === filters.field)?.name ?? ''] : [])
			])}
			bind:open={furtherOpen}
		>
			{#if spaces.length > 1}
				<FacetChips
					look="plain"
					label={m.facet_spaces()}
					items={spaces}
					selected={filters.spaces}
					onchange={(next) => set({ spaces: next })}
				/>
			{/if}
			{#if lookup.fields.length > 0}
				<Select
					aria-label={m.filter_field()}
					value={filters.field ?? ''}
					options={fields}
					onchange={(value) => set({ field: value || null })}
					class="h-9 w-full"
				/>
			{/if}
		</FilterSection>
	{/if}
	<FilterSection
		title={m.facet_facts()}
		summary={chosenSummary(filters.facts.map(factFilterLabel))}
		bind:open={factsOpen}
	>
		<FactFilter
			facts={filters.facts}
			admin={session.isAdmin}
			onchange={(next) => set({ facts: next })}
		/>
	</FilterSection>
</div>
