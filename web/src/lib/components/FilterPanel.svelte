<script lang="ts">
	import type { components } from '#lib/api/schema.ts';
	import FacetList, { type FacetItem } from '#lib/components/FacetList.svelte';
	import NativeSelect from '#lib/components/NativeSelect.svelte';
	import PeriodFacet from '#lib/components/PeriodFacet.svelte';
	import { isHex, isPalette } from '#lib/colors.ts';
	import type { Filters } from '#lib/filters.ts';
	import { spaceLabel, type Lookup, type Tag, type TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { ofScope, pathLabel } from '#lib/tags.ts';

	type Facets = components['schemas']['DocumentFacetsOut'];
	type ValueCount = components['schemas']['ValueCount'];

	// The filters of the document view, beside the list (or in a sheet on a phone): period,
	// contacts, types, topics and tags with how many documents each holds (`facets`; none
	// while searching: `showCounts`), most first; then the groups of contact and type, the
	// spaces and a field with a value. Within a group one of the chosen values must match,
	// tags and groups each.
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

	function set(patch: Partial<Filters>) {
		onchange({ ...filters, ...patch });
	}

	/** The counted values with a name, most first, and the chosen ones that hold none. */
	function counted(
		counts: readonly ValueCount[] | undefined,
		chosen: readonly string[],
		named: (id: string) => Omit<FacetItem, 'count'> | null
	): FacetItem[] {
		const items: FacetItem[] = [];
		for (const entry of counts ?? []) {
			const item = entry.id ? named(entry.id) : null;
			if (item) items.push({ ...item, count: showCounts ? entry.count : null });
		}
		for (const id of chosen) {
			const item = items.some((entry) => entry.id === id) ? null : named(id);
			if (item) items.push({ ...item, count: showCounts ? 0 : null });
		}
		return items;
	}

	function dot(tag: Tag): string | null {
		if (isPalette(tag.color)) return `var(--tag-${tag.color}-foreground)`;
		return tag.color && isHex(tag.color) ? tag.color : null;
	}

	const tags = $derived(new Map(lookup.tags.map((tag) => [tag.id, tag])));
	function tagItem(id: string, scope: TagScope, coloured: boolean) {
		const tag = tags.get(id);
		if (!tag || tag.scope !== scope) return null;
		return { id, label: tag.name, title: pathLabel(tag), dot: coloured ? dot(tag) : null };
	}
	function uncounted(scope: TagScope): FacetItem[] {
		return ofScope(lookup.tags, scope).map((tag) => ({
			id: tag.id,
			label: tag.name,
			title: pathLabel(tag),
			count: null
		}));
	}

	const contacts = $derived(
		counted(facets?.contacts, filters.contacts, (id) => {
			const contact = lookup.contacts.find((entry) => entry.id === id);
			return contact ? { id, label: contact.name } : null;
		})
	);
	const types = $derived(
		counted(facets?.document_types, filters.types, (id) => {
			const type = lookup.documentTypes.find((entry) => entry.id === id);
			return type ? { id, label: type.name } : null;
		})
	);
	const topics = $derived(
		counted(facets?.topics, filters.topics, (id) => tagItem(id, 'topic', false))
	);
	const documentTags = $derived(
		counted(facets?.tags, filters.tags, (id) => tagItem(id, 'document', true))
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
</script>

<div class="flex flex-col gap-5">
	<PeriodFacet
		years={facets?.years ?? []}
		undated={facets?.undated ?? 0}
		period={filters}
		{showCounts}
		onchange={(period) => set(period)}
	/>
	<FacetList
		title={m.facet_contacts()}
		items={contacts}
		selected={filters.contacts}
		onchange={(next) => set({ contacts: next })}
	/>
	<FacetList
		title={m.facet_types()}
		items={types}
		selected={filters.types}
		onchange={(next) => set({ types: next })}
	/>
	<FacetList
		title={m.facet_topics()}
		items={topics}
		selected={filters.topics}
		onchange={(next) => set({ topics: next })}
	/>
	<FacetList
		title={m.facet_tags()}
		items={documentTags}
		selected={filters.tags}
		onchange={(next) => set({ tags: next })}
	/>
	<FacetList
		title={m.facet_contact_groups()}
		items={uncounted('contact')}
		selected={filters.contactGroups}
		onchange={(next) => set({ contactGroups: next })}
		limit={4}
	/>
	<FacetList
		title={m.facet_type_groups()}
		items={uncounted('document_type')}
		selected={filters.typeGroups}
		onchange={(next) => set({ typeGroups: next })}
		limit={4}
	/>
	{#if spaces.length > 1}
		<FacetList
			title={m.facet_spaces()}
			items={spaces}
			selected={filters.spaces}
			onchange={(next) => set({ spaces: next })}
			limit={4}
		/>
	{/if}
	{#if lookup.fields.length > 0}
		<NativeSelect
			aria-label={m.filter_field()}
			value={filters.field ?? ''}
			options={fields}
			onchange={(value) => set({ field: value || null })}
			class="h-9 w-full"
		/>
	{/if}
</div>
