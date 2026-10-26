<script lang="ts" module>
	import type { LensFilter, LensSort } from '#lib/lenses.ts';
	import type { Layout } from '#lib/listing.ts';

	/** What a new lens takes from the documents page: its filters, words, sort and layout. */
	export interface LensDraft {
		filter: LensFilter;
		query: string | null;
		sort: LensSort | null;
		sortField: string | null;
		layout: Layout;
	}
</script>

<script lang="ts">
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import X from '@lucide/svelte/icons/x';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { cardLines } from '#lib/card-fields.ts';
	import ActiveFilters from '#lib/components/ActiveFilters.svelte';
	import DocumentCard from '#lib/components/DocumentCard.svelte';
	import EditorShell from '#lib/components/EditorShell.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { fieldTypeLabel } from '#lib/fields.ts';
	import { isFiltered } from '#lib/filters.ts';
	import { filtersOf, type Grouping, type Lens } from '#lib/lenses.ts';
	import { LIST_SORTS, sortLabel } from '#lib/listing.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import Chip from '#lib/components/Chip.svelte';

	type Listed = components['schemas']['ListedDocument'];

	// Add a lens (`initial` null: from the page's filters, words, sort and layout in `draft`) or
	// change one: its name, sort, deadline, grouping, layout and up to three card fields (moved
	// by dragging or with the arrows), with a preview of a card (`sample`, a document of the
	// list); delete one. The filters stand for reading: they are changed in the sidebar.
	let {
		open = $bindable(false),
		initial = null,
		draft,
		lookup,
		sample = null,
		today,
		onsaved,
		ondeleted
	}: {
		open?: boolean;
		initial?: Lens | null;
		draft: LensDraft;
		lookup: Lookup;
		sample?: Listed | null;
		today: Date;
		onsaved: (lens: Lens, created: boolean) => void;
		ondeleted: (id: string) => void;
	} = $props();

	const MAX_FIELDS = 3;
	const GROUPINGS: { value: Grouping; label: () => string }[] = [
		{ value: 'none', label: m.lens_grouping_none },
		{ value: 'month', label: m.lens_grouping_month },
		{ value: 'due', label: m.lens_grouping_due },
		{ value: 'document_type', label: m.lens_grouping_document_type },
		{ value: 'contact', label: m.lens_grouping_contact }
	];
	const PERIODS = {
		this_year: m.facet_this_year,
		last_12_months: m.facet_last_12_months,
		last_year: m.facet_last_year
	};

	let name = $state('');
	// '' as the list sorts; a sort by a field as `field:<id>` or `-field:<id>`.
	let sort = $state('');
	let dueId = $state('');
	let grouping = $state<Grouping>('none');
	let layout = $state<Layout>('grid');
	let cardIds = $state<string[]>([]);
	let dragged = $state<number | null>(null);

	$effect(() => {
		if (!open) return;
		name = initial?.name ?? '';
		const field = initial ? initial.sort_field_id : draft.sortField;
		const chosen = initial ? initial.sort : draft.sort;
		sort = chosen === null ? '' : field ? `${chosen}:${field}` : chosen;
		dueId = initial?.due_field_id ?? '';
		grouping = initial?.grouping ?? 'none';
		layout = initial?.layout ?? draft.layout;
		cardIds = [...(initial?.card_field_ids ?? [])];
	});

	const filter = $derived(initial?.filter ?? draft.filter);
	const query = $derived(initial ? initial.query : draft.query);
	// The filters as chips; a moving period stands as such above them.
	const shown = $derived({
		...filtersOf(filter, today),
		...(filter.document_period ? { dateFrom: null, dateTo: null } : {})
	});
	const empty = $derived(!query && !filter.document_period && !isFiltered(shown));
	const fields = $derived(lookup.fields);
	const named = (id: string) => fields.find((field) => field.id === id);
	const sortOptions = $derived([
		{ value: '', label: m.lens_sort_default() },
		...(query ? [{ value: 'relevance', label: sortLabel('relevance') }] : []),
		...LIST_SORTS.map((value) => ({ value, label: sortLabel(value) })),
		// The search index holds no field values: with words no sort by a field.
		...(query
			? []
			: fields
					.filter((field) => ['date', 'period', 'number', 'amount'].includes(field.data_type))
					.flatMap((field) =>
						(['field', '-field'] as const).map((value) => ({
							value: `${value}:${field.id}`,
							label: sortLabel(value, field)
						}))
					))
	]);
	const dueOptions = $derived([
		{ value: '', label: m.lens_due_none() },
		...fields
			.filter((field) => field.data_type === 'date')
			.map((field) => ({ value: field.id, label: field.name }))
	]);
	const addOptions = $derived([
		{ value: '', label: m.lens_field_add() },
		...fields
			.filter((field) => !cardIds.includes(field.id))
			.map((field) => ({ value: field.id, label: field.name }))
	]);
	const preview = $derived(
		sample
			? cardLines(
					sample.fields,
					cardIds.flatMap((id) => named(id) ?? []),
					dueId || null,
					today
				)
			: []
	);

	$effect(() => {
		// No grouping by deadline without one.
		if (grouping === 'due' && !dueId) grouping = 'none';
	});

	function move(from: number, to: number) {
		if (to < 0 || to >= cardIds.length || from === to) return;
		const next = [...cardIds];
		const [id] = next.splice(from, 1);
		next.splice(to, 0, id);
		cardIds = next;
	}

	async function save() {
		const [key, field] = sort.split(':');
		const body = {
			name: name.trim(),
			sort: (key || null) as LensSort | null,
			sort_field_id: field ?? null,
			grouping,
			layout,
			card_field_ids: cardIds,
			due_field_id: dueId || null
		};
		const saved = initial
			? await unwrap(
					api.PATCH('/api/v1/lenses/{id}', { params: { path: { id: initial.id } }, body })
				)
			: await unwrap(
					api.POST('/api/v1/lenses', {
						body: { ...body, filter: draft.filter, query: draft.query }
					})
				);
		toast.success(m.lens_saved({ name: saved.name }));
		onsaved(saved, initial === null);
	}

	async function remove() {
		if (!initial) return;
		await unwrap(api.DELETE('/api/v1/lenses/{id}', { params: { path: { id: initial.id } } }));
		toast.success(m.lens_deleted());
		open = false;
		ondeleted(initial.id);
	}
</script>

<EditorShell
	bind:open
	title={initial ? m.lens_edit() : m.lens_create()}
	shortTitle={m.lens_short()}
	submitLabel={m.save()}
	disabled={name.trim() === ''}
	action={save}
	ondelete={initial ? remove : undefined}
	deleteTitle={m.lens_delete({ name: initial?.name ?? '' })}
	deleteDescription={m.lens_delete_confirm()}
	class="sm:max-w-3xl"
>
	<div class="grid gap-6 sm:grid-cols-[minmax(0,1fr)_15rem]">
		<div class="flex min-w-0 flex-col gap-5">
			<Field.Field>
				<Field.Label for="lens-name">{m.lens_name()}</Field.Label>
				<Input id="lens-name" bind:value={name} maxlength={100} required />
			</Field.Field>

			<div class="flex flex-col gap-2">
				<span class="text-sm font-medium">{m.lens_filter()}</span>
				<div class="flex flex-wrap gap-2">
					{#if filter.document_period}
						<span
							class="inline-flex h-8 items-center rounded-full border border-primary/40 bg-panel px-3 text-sm text-brand"
						>
							{m.lens_period_moving({ period: PERIODS[filter.document_period]() })}
						</span>
					{/if}
					{#if query}
						<span class="inline-flex h-8 items-center rounded-full border px-3 text-sm">
							{m.lens_query({ words: query })}
						</span>
					{/if}
				</div>
				<ActiveFilters filters={shown} {lookup} readonly />
				{#if empty}
					<p class="text-sm text-muted-foreground">{m.lens_filter_none()}</p>
				{/if}
				<p class="text-sm text-muted-foreground">{m.lens_filter_hint()}</p>
			</div>

			<div class="grid gap-4 sm:grid-cols-2">
				<Field.Field>
					<Field.Label for="lens-sort">{m.lens_sort()}</Field.Label>
					<Select id="lens-sort" bind:value={sort} options={sortOptions} />
				</Field.Field>
				<Field.Field>
					<Field.Label for="lens-due">{m.lens_due()}</Field.Label>
					<Select id="lens-due" bind:value={dueId} options={dueOptions} />
					<Field.Description>{m.lens_due_hint()}</Field.Description>
				</Field.Field>
			</div>

			<div class="flex flex-col gap-2" role="group" aria-labelledby="lens-grouping">
				<span id="lens-grouping" class="text-sm font-medium">{m.lens_grouping()}</span>
				<div class="flex flex-wrap gap-1.5">
					{#each GROUPINGS as option (option.value)}
						{@const active = grouping === option.value}
						<Chip
							pressed={active}
							disabled={option.value === 'due' && !dueId}
							title={option.value === 'due' && !dueId ? m.lens_grouping_due_hint() : undefined}
							class="disabled:opacity-50"
							onclick={() => (grouping = option.value)}
						>
							{option.label()}
						</Chip>
					{/each}
				</div>
			</div>

			<div class="flex flex-col gap-2">
				<span id="lens-layout" class="text-sm font-medium">{m.lens_layout()}</span>
				<Segmented
					labelledby="lens-layout"
					equal
					class="w-56"
					value={layout}
					options={[
						{ value: 'grid', label: m.layout_grid() },
						{ value: 'list', label: m.layout_list() },
						{ value: 'stream', label: m.layout_stream() }
					]}
					onchange={(next) => (layout = next as Layout)}
				/>
			</div>

			<div class="flex flex-col gap-2">
				<span id="lens-fields" class="text-sm font-medium">{m.lens_fields()}</span>
				<ol class="flex flex-col gap-1.5" aria-labelledby="lens-fields">
					{#each cardIds as id, index (id)}
						{@const field = named(id)}
						<li
							draggable="true"
							ondragstart={() => (dragged = index)}
							ondragover={(event) => event.preventDefault()}
							ondrop={(event) => {
								event.preventDefault();
								if (dragged !== null) move(dragged, index);
								dragged = null;
							}}
							class="flex h-10 items-center gap-2 rounded-lg border bg-background pr-1 pl-2 text-sm"
						>
							<GripVertical class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
							<span class="min-w-0 flex-1 truncate">{field?.name ?? id}</span>
							{#if field}
								<span class="shrink-0 text-xs text-muted-foreground">
									{fieldTypeLabel(field.data_type)}
								</span>
							{/if}
							<button
								type="button"
								class="grid size-7 place-items-center rounded-full hover:bg-secondary disabled:opacity-30"
								aria-label={m.lens_field_up({ name: field?.name ?? id })}
								disabled={index === 0}
								onclick={() => move(index, index - 1)}
							>
								<ArrowUp class="size-3.5" aria-hidden="true" />
							</button>
							<button
								type="button"
								class="grid size-7 place-items-center rounded-full hover:bg-secondary disabled:opacity-30"
								aria-label={m.lens_field_down({ name: field?.name ?? id })}
								disabled={index === cardIds.length - 1}
								onclick={() => move(index, index + 1)}
							>
								<ArrowDown class="size-3.5" aria-hidden="true" />
							</button>
							<button
								type="button"
								class="grid size-7 place-items-center rounded-full hover:bg-secondary"
								aria-label={m.lens_field_remove({ name: field?.name ?? id })}
								onclick={() => (cardIds = cardIds.filter((entry) => entry !== id))}
							>
								<X class="size-3.5" aria-hidden="true" />
							</button>
						</li>
					{/each}
				</ol>
				{#if cardIds.length < MAX_FIELDS}
					<Select
						aria-label={m.lens_field_add()}
						value=""
						options={addOptions}
						onchange={(value) => value && (cardIds = [...cardIds, value])}
						class="h-9 w-full"
					/>
				{/if}
				<p class="text-sm text-muted-foreground">{m.lens_fields_hint()}</p>
			</div>
		</div>

		{#if sample}
			<div class="hidden flex-col gap-2 sm:flex">
				<span class="text-sm font-medium">{m.lens_preview()}</span>
				<div class="pointer-events-none" aria-hidden="true">
					<DocumentCard document={sample} {lookup} fields={preview} />
				</div>
				<p class="text-xs text-muted-foreground">{m.lens_preview_hint()}</p>
			</div>
		{/if}
	</div>
</EditorShell>
