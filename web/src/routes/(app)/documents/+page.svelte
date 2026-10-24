<script lang="ts">
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import Pencil from '@lucide/svelte/icons/pencil';
	import List from '@lucide/svelte/icons/list';
	import SearchIcon from '@lucide/svelte/icons/search';
	import Info from '@lucide/svelte/icons/info';
	import X from '@lucide/svelte/icons/x';
	import { onMount, tick, untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import type { components } from '#lib/api/schema.ts';
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
	import ActiveFilters from '#lib/components/ActiveFilters.svelte';
	import DocumentCard from '#lib/components/DocumentCard.svelte';
	import DocumentRow from '#lib/components/DocumentRow.svelte';
	import FilterPanel from '#lib/components/FilterPanel.svelte';
	import InboxMark from '#lib/components/InboxMark.svelte';
	import LensChanges from '#lib/components/LensChanges.svelte';
	import LensEditor, { type LensDraft } from '#lib/components/LensEditor.svelte';
	import Lenses from '#lib/components/Lenses.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import SortMenu from '#lib/components/SortMenu.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Sheet from '#lib/components/ui/sheet/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import {
		NO_FILTERS,
		apiQuery,
		isFiltered,
		parseFilters,
		writeFilters,
		type Filters
	} from '#lib/filters.ts';
	import { searchPlaces } from '#lib/header-search.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { cardLines } from '#lib/card-fields.ts';
	import { groupDocuments } from '#lib/grouping.ts';
	import { lensDiffers, lensFilter, lensParams, type Lens, type LensSort } from '#lib/lenses.ts';
	import {
		FIELD_SORTS,
		LIST_SORTS,
		SEARCH_SORTS,
		isFieldSort,
		rememberSort,
		rememberLayout,
		rememberedLayout,
		sortFieldOf,
		sortLabel,
		sortShort,
		sortOf,
		type ListSort,
		type Sort,
		type FieldSort,
		type Layout
	} from '#lib/listing.ts';
	import { loadLookup, type Lookup } from '#lib/masterdata.svelte.ts';
	import { openLens } from '#lib/open-lens.svelte.ts';
	import { PagedList } from '#lib/paging.svelte.ts';
	import { reasonText } from '#lib/reasons.ts';
	import { SearchNote } from '#lib/search-note.svelte.ts';
	import { warmSearch } from '#lib/search-warm.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { scope } from '#lib/scope.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// The documents (the archive): listed (newest document date first) or, with words in `q`,
	// searched (by relevance), with the same filters; sorted as chosen, as a grid or a list, by
	// month under headings while sorted by a date. The
	// URL holds the words, the filters and the sort; grid or list and the last sort are
	// remembered. No lanes here: a document that stands open in the inbox says so, with a link.
	// Documents are uploaded in the inbox.
	type Document = components['schemas']['ListedDocument'];
	type Segment = components['schemas']['SnippetSegment'];
	type Item = { document: Document; snippet: Segment[] };
	type Facets = components['schemas']['DocumentFacetsOut'];

	const params = $derived(new URLSearchParams(page.url.search));
	const filters = $derived(parseFilters(params));
	const query = $derived(params.get('q')?.trim() ?? '');
	const searching = $derived(query !== '');
	const sort = $derived(sortOf(params, searching));
	const sortField = $derived(sortFieldOf(params, searching));
	// The search field follows the URL (back button, links) until the user types.
	let text = $derived(query);
	let layout = $state<Layout>(rememberedLayout());
	let lookup = $state<Lookup | null>(null);
	let lookupError = $state<string | null>(null);
	// How many documents each value of the filters holds; the words of a search aside.
	let facets = $state<Facets | null>(null);
	let filtersOpen = $state(false);
	// The user's lenses; the open one is in the URL (`lens`).
	let lenses = $state<Lens[]>([]);
	const lens = $derived(lenses.find((entry) => entry.id === params.get('lens')) ?? null);
	const today = new Date();
	// The editor of a lens: a new one (null) from the page as it stands, or the open one.
	let editorOpen = $state(false);
	let editing = $state<Lens | null>(null);
	const draft = $derived<LensDraft>({
		filter: lensFilter(filters, today),
		query: query || null,
		sort: params.has('sort') ? (sort as LensSort) : null,
		sortField,
		layout
	});

	// The page differs from the open lens: keep it there, as a new lens, or go back.
	const changed = $derived(lens !== null && lensDiffers(lens, params, today));
	let keeping = $state(false);

	async function keep() {
		if (!lens) return;
		keeping = true;
		try {
			const kept = await unwrap(
				api.PATCH('/api/v1/lenses/{id}', {
					params: { path: { id: lens.id } },
					body: {
						filter: draft.filter,
						query: draft.query,
						sort: draft.sort,
						sort_field_id: draft.sortField
					}
				})
			);
			toast.success(m.lens_saved({ name: kept.name }));
			await loadLenses();
		} catch (error) {
			toast.error(describeError(error));
		} finally {
			keeping = false;
		}
	}

	function edit(target: Lens | null) {
		editing = target;
		editorOpen = true;
	}

	async function saved(saved: Lens, created: boolean) {
		await loadLenses();
		if (created) {
			go(lensParams(saved, today));
			return;
		}
		// The page takes the lens's sort and layout; its filters stay as they stand.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const next = new URLSearchParams(page.url.search);
		if (saved.sort) next.set('sort', saved.sort);
		else next.delete('sort');
		if (saved.sort_field_id) next.set('sort_field', saved.sort_field_id);
		else next.delete('sort_field');
		layout = saved.layout;
		go(next);
	}

	async function deleted(id: string) {
		await loadLenses();
		if (params.get('lens') === id) go(new URLSearchParams());
	}

	// The header's search names the open lens.
	$effect(() => {
		openLens.name = lens?.name ?? null;
		return () => (openLens.name = null);
	});

	// Opening a lens shows its layout (not remembered: that is the choice outside lenses).
	let shownLens: string | null = null;
	$effect(() => {
		if (lens && lens.id !== shownLens) layout = lens.layout;
		shownLens = lens?.id ?? null;
	});
	const activeFilters = $derived(
		filters.contacts.length +
			filters.types.length +
			filters.tags.length +
			filters.contactGroups.length +
			filters.typeGroups.length +
			filters.topics.length +
			filters.spaces.length +
			(filters.field ? 1 : 0) +
			(filters.dateFrom || filters.dateTo ? 1 : 0)
	);

	async function loadLenses() {
		try {
			lenses = await unwrap(api.GET('/api/v1/lenses'));
		} catch {
			// Without lenses the documents stand as ever.
			lenses = [];
		}
	}

	async function loadFacets() {
		const query = apiQuery(filters, scope.allUsers);
		try {
			facets = await unwrap(api.GET('/api/v1/documents/facets', { params: { query } }));
		} catch {
			// The list stands without counts; it says what went wrong itself.
			facets = null;
		}
	}

	// How the search searched: by words alone and why, the meaning still being made or ready.
	const searchNote = new SearchNote();

	const list = new PagedList<Item>(async (after) => {
		const base = apiQuery(filters, scope.allUsers);
		if (searching) {
			const words = query;
			const data = await unwrap(
				api.GET('/api/v1/documents/search', {
					params: {
						query: {
							...base,
							q: words,
							// A search never sorts by a field (`sortOf`).
							sort: sort as Exclude<Sort, FieldSort>,
							offset: (after as number | null) ?? 0,
							semantic_ratio: searchNote.ratio(words)
						}
					}
				})
			);
			if (after === null) searchNote.answered(words, data);
			const items = data.items.map((hit) => ({ document: hit.document, snippet: hit.snippet }));
			return { items, next: data.next_offset, total: data.estimated_total };
		}
		const data = await unwrap(
			api.GET('/api/v1/documents', {
				params: {
					query: {
						...base,
						sort: sort as ListSort,
						sort_field_id: sortField ?? undefined,
						cursor: (after as string | null) ?? undefined
					}
				}
			})
		);
		return {
			items: data.items.map((document) => ({ document, snippet: [] })),
			next: data.next_cursor
		};
	});

	// How many documents the filters leave: estimated while searching.
	const shownCount = $derived(searching ? list.total : (facets?.total ?? null));

	// While a search waits for its first page, the hint says when it takes long.
	$effect(() => searchNote.waiting(searching && list.loading && !list.loaded));
	// The index is not reachable: the list without words still works.
	const indexDown = $derived(
		list.error instanceof ApiError &&
			list.error.problem?.reason?.code === 'search_index_unavailable'
	);
	const note = $derived(searching ? searchNote.about(query) : null);

	// Reload when the words, filters or sort change, and after a reconnect of the event stream.
	$effect(() => {
		void page.url.search;
		void scope.allUsers;
		void events.generation;
		void list.reload();
		void loadFacets();
	});

	// Again when an admin switches the reach: the spaces of the filter follow it.
	let reachBefore = scope.allUsers;
	$effect(() => {
		const reach = scope.allUsers;
		if (reach === reachBefore) return;
		reachBefore = reach;
		untrack(() =>
			loadLookup().then(
				(value) => (lookup = value),
				(error) => (lookupError = describeError(error))
			)
		);
	});

	onMount(() => {
		loadLookup().then(
			(value) => (lookup = value),
			(error) => (lookupError = describeError(error))
		);
		void loadLenses();
		// Opened from the search icon of a narrow header: the field takes the focus.
		if (location.hash === '#search') {
			void tick().then(() => {
				// The field that shows at this width (`header-search.ts`).
				const fields = document.querySelectorAll<HTMLInputElement>('[data-page-search]');
				[...fields].find((field) => field.offsetParent !== null)?.focus();
			});
		}
		let timer: ReturnType<typeof setTimeout> | undefined;
		// Events are thin: fetch the list again, at most once in a while.
		const refresh = () => {
			clearTimeout(timer);
			timer = setTimeout(() => {
				void list.refresh();
				void loadFacets();
			}, 400);
		};
		const stop = events.subscribe(refresh);
		const stopMeaning = events.on('search.meaning_ready', (event) =>
			searchNote.meaningReady(String(event.query ?? ''))
		);
		return () => {
			clearTimeout(timer);
			stop();
			stopMeaning();
		};
	});

	function go(next: URLSearchParams) {
		const search = next.toString();
		void goto(search ? `?${search}` : page.url.pathname, { reset: false });
	}

	function change(next: Filters) {
		go(writeFilters(new URLSearchParams(page.url.search), next));
	}

	function search(term: string) {
		// Built and handed on at once, nothing reacts to it.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const next = new URLSearchParams(page.url.search);
		if (term) next.set('q', term);
		else next.delete('q');
		// A list sort may not suit a search and back: the remembered one of the mode holds.
		next.delete('sort');
		next.delete('sort_field');
		go(next);
	}

	function sortBy(value: string) {
		const chosen = value as Sort;
		rememberSort(chosen, searching);
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const next = new URLSearchParams(page.url.search);
		next.set('sort', chosen);
		if (!isFieldSort(chosen)) next.delete('sort_field');
		go(next);
	}

	function show(next: Layout) {
		layout = next;
		rememberLayout(next);
	}

	// While a list sorts by a field (a lens may), its two directions are offered too.
	const sorts = $derived.by(() => {
		const standard = (searching ? SEARCH_SORTS : LIST_SORTS).map((value) => ({
			value,
			label: sortLabel(value)
		}));
		const field = lookup?.fields.find((entry) => entry.id === sortField);
		if (!field) return standard;
		return [
			...standard,
			...FIELD_SORTS.map((value) => ({ value, label: sortLabel(value, field) }))
		];
	});

	// Without a lens, sorted by a date, the documents stand by month under headings; a lens
	// groups as it says.
	const groups = $derived(
		groupDocuments(list.items, lens?.grouping ?? 'sort', (item) => item.document, {
			sort,
			dueField: lens?.due_field_id ?? null,
			today,
			lookup
		})
	);
	function linesOf(item: Item) {
		return cardFields.length > 0
			? cardLines(item.document.fields, cardFields, lens?.due_field_id ?? null, today)
			: [];
	}
	// The fields a lens shows on its cards, in its order.
	const cardFields = $derived(
		(lens?.card_field_ids ?? []).flatMap(
			(id) => lookup?.fields.find((field) => field.id === id) ?? []
		)
	);
</script>

<svelte:head><title>{m.nav_documents()} · {m.app_name()}</title></svelte:head>

{#snippet snippetLine(item: Item)}
	{#if item.snippet.length > 0}
		<span class="line-clamp-2 text-sm text-muted-foreground">
			{#each item.snippet as part, index (index)}
				{#if part.match}
					<mark class="rounded bg-lane-yellow px-0.5 text-lane-yellow-foreground">{part.text}</mark>
				{:else}{part.text}{/if}
			{/each}
		</span>
	{/if}
{/snippet}

<!-- The page's own search, where the header has none (`header-search.ts`): on a phone in the
row of filters, on a desktop narrow by the title. -->
{#snippet searchForm(compact: boolean)}
	{@const places = searchPlaces(session.isAdmin)}
	<form
		role="search"
		class={cn(
			'min-w-0 items-center gap-2 rounded-full border border-input bg-background focus-within:border-ring',
			compact
				? cn('h-9 w-64 pr-1 pl-3', places.title)
				: cn('flex h-11 flex-1 pr-1.5 pl-4', places.phone)
		)}
		onsubmit={(event) => {
			event.preventDefault();
			search(text.trim());
		}}
	>
		<SearchIcon class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
		<input
			data-page-search
			bind:value={text}
			type="search"
			aria-label={m.documents_search_label()}
			placeholder={lens ? m.header_search_in({ name: lens.name }) : m.search_placeholder()}
			oninput={() => warmSearch()}
			class="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden"
		/>
		{#if query}
			<Button
				type="button"
				variant="ghost"
				size="icon"
				class="size-7"
				aria-label={m.documents_search_clear()}
				onclick={() => {
					text = '';
					search('');
				}}
			>
				<X aria-hidden="true" />
			</Button>
		{/if}
	</form>
{/snippet}

{#snippet sortMenu(compact: boolean)}
	<SortMenu
		options={sorts}
		value={sort}
		short={sortShort(
			sort,
			lookup?.fields.find((field) => field.id === sortField)
		)}
		onchange={sortBy}
		{compact}
	/>
{/snippet}

{#snippet lensLinks(variant: 'list' | 'chips')}
	<Lenses
		{lenses}
		{variant}
		active={lens?.id ?? null}
		href={(entry) => `?${lensParams(entry, today)}`}
		allHref={page.url.pathname}
		{changed}
		onadd={lookup ? () => edit(null) : undefined}
	/>
{/snippet}

{#snippet filterPanel()}
	{#if lookup}
		<FilterPanel {filters} {lookup} {facets} showCounts={!searching} onchange={change} />
	{/if}
{/snippet}

<div class="flex flex-col gap-6" data-roomy>
	<div class="flex flex-col gap-3">
		<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
			<h1 class="text-[1.75rem] font-semibold tracking-tight">
				{lens?.name ?? m.nav_documents()}
			</h1>
			{#if searching && list.total !== null && list.loaded}
				<p class="text-sm text-muted-foreground" aria-live="polite">
					{m.search_total({ count: formatNumber(list.total) })}
				</p>
			{:else if facets && !searching}
				<p class="text-sm text-muted-foreground" aria-live="polite">
					{m.documents_total({ count: formatNumber(facets.total) })}
				</p>
			{/if}
			<div class="ml-auto flex items-center gap-2">
				<div class="hidden items-center gap-2 lg:flex">
					{@render searchForm(true)}
					{@render sortMenu(false)}
					<Segmented
						names="hidden"
						label={m.layout_label()}
						value={layout}
						options={[
							{ value: 'grid', label: m.layout_grid(), icon: LayoutGrid },
							{ value: 'list', label: m.layout_list(), icon: List }
						]}
						onchange={(next) => show(next as Layout)}
					/>
				</div>
				{#if lens && lookup}
					<Button
						variant="outline"
						class="max-lg:size-10 max-lg:px-0"
						aria-label={m.lens_edit()}
						title={m.lens_edit()}
						onclick={() => edit(lens)}
					>
						<Pencil aria-hidden="true" />
						<span class="max-lg:hidden">{m.lens_edit()}</span>
					</Button>
				{/if}
			</div>
		</div>
		<div class="lg:hidden">
			{@render lensLinks('chips')}
		</div>
	</div>

	<div class="flex gap-8">
		<aside class="hidden w-72 shrink-0 lg:block" aria-label={m.filters_title()}>
			<div
				class="sticky top-20 flex max-h-[calc(100dvh-6rem)] flex-col gap-2 overflow-y-auto pr-1 pb-4"
			>
				{@render lensLinks('list')}
				{@render filterPanel()}
			</div>
		</aside>
		<div class="flex min-w-0 flex-1 flex-col gap-6">
			<!-- Empty on a desktop without filters, words or changes: then it takes no room, and
			the list stands level with the lenses. -->
			<div
				class={[
					'flex flex-col gap-3',
					!(changed || query || isFiltered(filters) || lookupError) && 'lg:hidden'
				]}
			>
				<!-- Below the desktop the filters, sort and layout stand in a row, on a phone beside
				the page's own search (the header has only a magnifier there). -->
				<div class="flex items-center justify-end gap-2 lg:hidden">
					{@render searchForm(false)}
					<Sheet.Root bind:open={filtersOpen}>
						<Sheet.Trigger
							class="relative grid size-11 shrink-0 place-items-center rounded-xl border border-input bg-background hover:bg-secondary lg:hidden"
							aria-label={m.filters_open()}
						>
							<SlidersHorizontal class="size-4" aria-hidden="true" />
							{#if activeFilters > 0}
								<span
									class="absolute -top-1 -right-1 grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1 text-xs font-semibold text-primary-foreground tabular-nums"
									aria-hidden="true"
								>
									{activeFilters}
								</span>
							{/if}
						</Sheet.Trigger>
						<!-- Title and close stay at the top, reset and show at the bottom; between them
						the filters scroll. -->
						<Sheet.Content
							side="bottom"
							showCloseButton={false}
							class="max-h-[85dvh] gap-0 rounded-t-2xl"
						>
							<Sheet.Header class="flex-row items-center justify-between border-b py-2 pr-2 pl-4">
								<Sheet.Title>{m.filters_title()}</Sheet.Title>
								<Sheet.Close>
									{#snippet child({ props })}
										<Button variant="ghost" size="icon" {...props} aria-label={m.close()}>
											<X aria-hidden="true" />
										</Button>
									{/snippet}
								</Sheet.Close>
							</Sheet.Header>
							<div class="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
								{@render filterPanel()}
							</div>
							<Sheet.Footer class="flex-row border-t py-3">
								<Button
									variant="ghost"
									disabled={!isFiltered(filters)}
									onclick={() => change(NO_FILTERS)}
								>
									{m.filters_reset()}
								</Button>
								<Button class="flex-1" onclick={() => (filtersOpen = false)}>
									{shownCount === null
										? m.filters_show_all()
										: m.filters_show({ count: formatNumber(shownCount) })}
								</Button>
							</Sheet.Footer>
						</Sheet.Content>
					</Sheet.Root>
					{@render sortMenu(true)}
					<button
						type="button"
						class="grid size-11 shrink-0 place-items-center rounded-xl border border-input bg-background hover:bg-secondary"
						aria-label={layout === 'grid' ? m.layout_list() : m.layout_grid()}
						onclick={() => show(layout === 'grid' ? 'list' : 'grid')}
					>
						{#if layout === 'grid'}
							<List class="size-4" aria-hidden="true" />
						{:else}
							<LayoutGrid class="size-4" aria-hidden="true" />
						{/if}
					</button>
				</div>
				{#if lens && changed}
					<LensChanges
						name={lens.name}
						busy={keeping}
						onsave={keep}
						onsaveas={() => edit(null)}
						ondiscard={() => lens && go(lensParams(lens, today))}
					/>
				{/if}
				{#if lookup}
					<ActiveFilters
						{filters}
						{lookup}
						onchange={change}
						{query}
						onclearquery={() => {
							text = '';
							search('');
						}}
					/>
				{:else if lookupError}
					<p class="text-destructive" role="alert">{lookupError}</p>
				{/if}
			</div>

			{#if searching && searchNote.slow}
				<p class="text-sm text-muted-foreground" aria-live="polite">{m.search_slow()}</p>
			{:else if note}
				<div
					class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border bg-card px-3 py-2 text-sm text-muted-foreground"
					aria-live="polite"
				>
					<Info class="size-4 shrink-0" aria-hidden="true" />
					<p class="min-w-0 flex-1">
						{reasonText(note.reason)}
						{#if note.pending}{m.search_meaning_pending()}{/if}
					</p>
					{#if note.ready}
						<Button
							variant="outline"
							size="sm"
							onclick={() => {
								searchNote.withMeaning();
								void list.reload();
							}}
						>
							{m.search_with_meaning()}
						</Button>
					{/if}
				</div>
			{/if}

			{#if list.error}
				<div class="flex flex-col items-start gap-3" role="alert">
					<p class="text-destructive">{describeError(list.error)}</p>
					<div class="flex flex-wrap gap-2">
						<Button variant="outline" onclick={() => list.reload()}>{m.retry()}</Button>
						{#if indexDown}
							<Button
								variant="outline"
								onclick={() => {
									text = '';
									search('');
								}}
							>
								{m.search_without_words()}
							</Button>
						{/if}
					</div>
				</div>
			{:else if list.empty}
				<p
					class="rounded-2xl border border-dashed bg-card px-6 py-16 text-center text-muted-foreground"
				>
					{isFiltered(filters)
						? m.documents_none_filtered()
						: searching
							? m.search_none()
							: m.documents_none()}
				</p>
			{:else}
				<div class="flex flex-col gap-6" aria-busy={list.loading}>
					{#each groups as group (group.key)}
						<section class="flex flex-col gap-3" aria-label={group.label ?? undefined}>
							{#if group.label !== null}
								<h2
									class={[
										'flex items-center gap-3 text-[0.95rem] font-semibold',
										group.tone === 'overdue' && 'text-lane-red-foreground',
										group.tone === 'soon' && 'text-lane-yellow-foreground'
									]}
								>
									{group.label}
									{#if lens}
										<span class="text-sm font-normal text-muted-foreground tabular-nums">
											{formatNumber(group.items.length)}
										</span>
									{/if}
									<span aria-hidden="true" class="h-px flex-1 bg-border"></span>
								</h2>
							{/if}
							{#if layout === 'grid'}
								<ul
									class="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(13rem,1fr))]"
								>
									{#each group.items as item (item.document.id)}
										<li class="min-w-0">
											<DocumentCard document={item.document} {lookup} fields={linesOf(item)}>
												{@render snippetLine(item)}
											</DocumentCard>
										</li>
									{/each}
								</ul>
							{:else}
								<ul class="flex flex-col gap-2">
									{#each group.items as item (item.document.id)}
										<li>
											<DocumentRow document={item.document} {lookup} fields={linesOf(item)}>
												{@render snippetLine(item)}
												{#snippet aside()}
													{#if item.document.in_inbox}<InboxMark id={item.document.id} />{/if}
												{/snippet}
											</DocumentRow>
										</li>
									{/each}
								</ul>
							{/if}
						</section>
					{/each}
				</div>
				{#if list.loading && !list.loaded}
					<p class="text-muted-foreground">{m.loading()}</p>
				{/if}
				{#if list.hasMore}
					<div class="flex justify-center">
						<Button variant="outline" disabled={list.loading} onclick={() => list.more()}>
							{m.load_more()}
						</Button>
					</div>
				{/if}
			{/if}
		</div>
	</div>
</div>

{#if lookup}
	<LensEditor
		bind:open={editorOpen}
		initial={editing}
		{draft}
		{lookup}
		sample={list.items[0]?.document ?? null}
		{today}
		onsaved={saved}
		ondeleted={deleted}
	/>
{/if}
