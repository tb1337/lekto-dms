<script lang="ts" module>
	import type { components } from '#lib/api/schema.ts';
	import type { Node } from '#lib/pipeline.ts';
	import type { RankKind } from '#lib/step-details.ts';

	/** What a step's details need beyond its entry: the files, the reading and the text are the
	 * document's current ones, so they belong to the latest run of their step only. */
	export interface DetailContext {
		documentId: string;
		/** The latest run in which each step left an entry. */
		latest: Partial<Record<Node, number>>;
		files: components['schemas']['DocumentFilesOut'] | null;
		/** The pages the latest reading read poorly, by number. */
		poor: readonly number[];
		thresholds: Partial<Record<RankKind, number>>;
		/** The document tab with the text. */
		textHref: string;
		/** The document tab at a page. */
		pageHref: (page: number) => string;
	}
</script>

<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Info from '@lucide/svelte/icons/info';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { pageImageHref } from '#lib/document-view.ts';
	import { fileKind, fileSize } from '#lib/file-passport.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { object } from '#lib/signals.ts';
	import {
		classifierRanks,
		neighbourList,
		ocrNotes,
		pageBars,
		pageCharacters
	} from '#lib/step-details.ts';
	import { DOT, MARK } from '#lib/step-look.ts';
	import { cn } from '#lib/utils.ts';

	type LogEntry = components['schemas']['LogEntry'];
	type Stored = components['schemas']['StoredFileOut'];

	// What a step did in one entry of the log, drawn (Tobi, 23.10.2026): for the text
	// recognition the original beside the archive, notes and how well each page was read; the
	// page images; the characters of each page and the way to the text; the classifier's classes
	// against its threshold; the similar documents with their similarity. What the text names
	// stands in the rows of the entry (`FactRows`).
	let {
		entry,
		lookup,
		context
	}: { entry: LogEntry; lookup: Lookup | null; context: DetailContext } = $props();

	const output = $derived(object(entry.output));
	// The files, the page images and the text are the latest run's.
	const latest = $derived(context.latest[entry.node] === entry.run);
	// What the text effect depends on, as values: `context` is a fresh object on every change
	// of the processing view, and the text is only asked for again when these change.
	const node = $derived(entry.node);
	const documentId = $derived(context.documentId);
	// Bars of unsure words reach the top at a fifth of the page: well read pages stay low.
	const unsureHeight = (value: number) => `${Math.max(4, Math.min(100, value * 500))}%`;
	const pages = $derived(typeof output.pages === 'number' ? output.pages : 0);
	const filePages = (count: number) =>
		count === 1 ? m.details_file_pages_one() : m.details_file_pages({ count: formatNumber(count) });

	// The characters of each page, from the text (only for the latest reading of it, and only
	// as long as it comes in a few pieces).
	const MAX_TEXT = 400_000;
	let characters = $state<number[] | null>(null);
	$effect(() => {
		if (node !== 'parse' || !latest) return;
		const id = documentId;
		let stale = false;
		void (async () => {
			try {
				let text = '';
				let offset: number | null = 0;
				while (offset !== null) {
					const piece: components['schemas']['DocumentTextOut'] = await unwrap(
						api.GET('/api/v1/documents/{id}/text', {
							params: { path: { id }, query: { offset } }
						})
					);
					if (typeof piece?.text !== 'string' || piece.total_length > MAX_TEXT) return;
					text += piece.text;
					offset = piece.next_offset ?? null;
				}
				if (!stale) characters = pageCharacters(text);
			} catch {
				// Without the text the details keep the totals.
			}
		})();
		return () => {
			stale = true;
		};
	});
	const most = $derived(Math.max(1, ...(characters ?? [])));
	const total = $derived(typeof output.characters === 'number' ? output.characters : null);
</script>

{#snippet tile(label: string, file: Stored | null)}
	<div class="flex min-w-0 flex-col gap-0.5 rounded-xl border bg-card px-3 py-2.5">
		<span class="text-xs text-muted-foreground">{label}</span>
		{#if file}
			<span class="font-semibold">{fileKind(file) || '–'}</span>
			<span class="text-xs text-muted-foreground tabular-nums">
				{[fileSize(file.size), file.metadata?.pages ? filePages(file.metadata.pages) : null]
					.filter(Boolean)
					.join(' · ')}
			</span>
		{:else}
			<span class="text-sm text-muted-foreground">{m.files_no_archive()}</span>
		{/if}
	</div>
{/snippet}

{#snippet bar(fill: number, threshold: number | null, faint: boolean)}
	<span class="relative h-1.5 rounded-full bg-muted" aria-hidden="true">
		<span
			class={cn('block h-1.5 rounded-full bg-note-foreground', faint && 'opacity-60')}
			style:width="{fill * 100}%"
		></span>
		{#if threshold !== null}
			<span
				class="absolute -top-1 h-3.5 w-0.5 -translate-x-1/2 rounded-full bg-foreground/70"
				style:left="{threshold * 100}%"
			></span>
		{/if}
	</span>
{/snippet}

<div class="@container flex flex-col gap-3">
	{#if entry.node === 'ocr'}
		{@const notes = ocrNotes(output)}
		{@const bars = pageBars(output)}
		{#if latest && context.files}
			<div
				role="group"
				aria-label={m.details_files()}
				class="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 @lg:max-w-xl"
			>
				{@render tile(m.files_original(), context.files.original)}
				<ArrowRight class="size-4 text-muted-foreground" aria-hidden="true" />
				{@render tile(m.files_archive(), context.files.archive)}
			</div>
		{/if}
		{#if notes.length > 0}
			<ul class="flex flex-col gap-1 text-sm">
				{#each notes as note (note)}
					<li class="flex items-start gap-2">
						<Info class="mt-0.5 size-4 shrink-0 text-note-foreground" aria-hidden="true" />
						{note}
					</li>
				{/each}
			</ul>
		{/if}
		{#if bars.length > 0}
			{@const poor = latest ? context.poor : []}
			<figure class="m-0 flex flex-col gap-2">
				<figcaption class="flex flex-wrap items-baseline gap-x-2 text-sm">
					<span class="font-medium">{m.details_reading()}</span>
					<span class="text-xs text-muted-foreground">{m.details_reading_hint()}</span>
				</figcaption>
				<ol class="flex items-end gap-2 overflow-x-auto pb-1">
					{#each bars as page (page.page)}
						{@const weak = poor.includes(page.page)}
						<li class="flex w-14 shrink-0 flex-col items-center gap-1" title={page.text}>
							<span
								class="flex h-14 w-full items-end overflow-hidden rounded-md bg-muted"
								aria-hidden="true"
							>
								<span
									class={cn('w-full', weak ? MARK.yellow : 'bg-primary')}
									style:height={unsureHeight(page.unsure)}
								></span>
							</span>
							<span class="text-xs font-medium tabular-nums" aria-hidden="true">{page.label}</span>
							<span class="text-[11px] whitespace-nowrap text-muted-foreground" aria-hidden="true"
								>{m.details_page_short({ page: String(page.page) })}</span
							>
							<span class="text-[11px] whitespace-nowrap text-muted-foreground" aria-hidden="true"
								>{m.details_page_words({ words: formatNumber(page.words) })}</span
							>
							<span class="sr-only">{page.text}{weak ? ` (${m.details_poor()})` : ''}</span>
						</li>
					{/each}
				</ol>
				{#if poor.length > 0}
					<p class="flex items-center gap-1.5 text-xs text-muted-foreground" aria-hidden="true">
						<span class={cn('size-2.5 rounded-sm', DOT.yellow)}></span>{m.details_poor()}
					</p>
				{/if}
			</figure>
		{/if}
	{:else if entry.node === 'pages'}
		{#if latest && pages > 0}
			<figure class="m-0 flex flex-col gap-2">
				<figcaption class="text-sm font-medium">{m.details_page_images()}</figcaption>
				<ol class="flex gap-2 overflow-x-auto pb-1">
					{#each Array.from({ length: pages }, (_, index) => index + 1) as number (number)}
						<li class="shrink-0">
							<a
								href={context.pageHref(number)}
								class="group flex flex-col items-center gap-1 rounded-lg focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
								title={m.details_page_open({ page: String(number) })}
								aria-label={m.details_page_open({ page: String(number) })}
							>
								<img
									src={pageImageHref(context.documentId, number)}
									alt=""
									loading="lazy"
									decoding="async"
									class="h-24 w-auto max-w-20 rounded-md border bg-surface object-contain transition-shadow group-hover:shadow-md"
								/>
								<span class="text-[11px] text-muted-foreground"
									>{m.details_page_short({ page: String(number) })}</span
								>
							</a>
						</li>
					{/each}
				</ol>
			</figure>
		{:else if pages > 0}
			<p class="text-sm">{m.summary_page_images({ count: pages })}</p>
		{/if}
	{:else if entry.node === 'parse'}
		{#if total !== null}
			<p class="text-sm">
				{pages > 1
					? m.details_characters_total({
							count: formatNumber(total),
							pages: formatNumber(pages),
							average: formatNumber(Math.round(total / pages))
						})
					: m.details_characters_one_page({ count: formatNumber(total) })}
			</p>
		{/if}
		{#if latest && characters && characters.length > 1}
			<figure class="m-0 flex flex-col gap-2">
				<figcaption class="text-sm font-medium">{m.details_characters()}</figcaption>
				<ol class="flex items-end gap-2 overflow-x-auto pb-1">
					{#each characters as amount, index (index)}
						{@const label = m.details_page_characters({
							page: String(index + 1),
							count: formatNumber(amount)
						})}
						<li class="flex w-14 shrink-0 flex-col items-center gap-1" title={label}>
							<span
								class="flex h-12 w-full items-end overflow-hidden rounded-md bg-muted"
								aria-hidden="true"
							>
								<span class="w-full bg-primary" style:height="{Math.max(4, (amount / most) * 100)}%"
								></span>
							</span>
							<span class="text-xs font-medium tabular-nums" aria-hidden="true"
								>{formatNumber(amount)}</span
							>
							<span class="text-[11px] whitespace-nowrap text-muted-foreground" aria-hidden="true"
								>{m.details_page_short({ page: String(index + 1) })}</span
							>
							<span class="sr-only">{label}</span>
						</li>
					{/each}
				</ol>
			</figure>
		{/if}
		{#if latest}
			<a href={context.textHref} class="self-start text-sm text-brand hover:underline"
				>{m.details_text_open()}</a
			>
		{/if}
	{:else if entry.node === 'signal_classifier'}
		{@const groups = classifierRanks(output, lookup, context.thresholds)}
		<div class="grid gap-x-8 gap-y-4 @xl:grid-cols-2">
			{#each groups as group (group.kind)}
				<div class="flex min-w-0 flex-col gap-1.5">
					<h4 class="text-xs font-normal text-muted-foreground">
						{group.label}{#if group.threshold !== null}<span>
								· {m.details_threshold({
									value: formatNumber(group.threshold, { style: 'percent' })
								})}</span
							>{/if}
					</h4>
					{#if group.ranks.length === 0}
						<p class="text-sm text-muted-foreground">{m.signal_none()}</p>
					{:else}
						<ol class="flex flex-col gap-1.5">
							{#each group.ranks as rank, index (index)}
								<li class="grid grid-cols-[minmax(0,1fr)_5.5rem_3rem] items-center gap-2.5 text-sm">
									<span class="truncate" title={rank.name}>{rank.name}</span>
									{@render bar(rank.share, group.threshold, index > 0)}
									<span class="text-right text-xs tabular-nums">{rank.label}</span>
								</li>
							{/each}
						</ol>
					{/if}
				</div>
			{/each}
		</div>
		{#if groups.some((group) => group.threshold !== null)}
			<p class="text-xs text-muted-foreground">{m.details_threshold_hint()}</p>
		{/if}
	{:else if entry.node === 'signal_neighbours'}
		{@const neighbours = neighbourList(output, lookup)}
		{#if neighbours.length === 0}
			<p class="text-sm text-muted-foreground">{m.summary_neighbours_none()}</p>
		{:else}
			<ol class="flex flex-col gap-1.5">
				{#each neighbours as neighbour, index (index)}
					<li
						class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 text-sm @lg:grid-cols-[6rem_minmax(0,1fr)_7rem_3rem]"
					>
						{#if neighbour.href}
							<a href={neighbour.href} class="whitespace-nowrap text-brand hover:underline"
								>{neighbour.title}</a
							>
						{:else}
							<span class="whitespace-nowrap">{neighbour.title}</span>
						{/if}
						<span class="truncate text-muted-foreground" title={neighbour.about}
							>{neighbour.about}</span
						>
						{#if neighbour.similarity !== null && neighbour.label !== null}
							<span class="max-@lg:hidden contents">
								{@render bar(neighbour.similarity, null, false)}
							</span>
							<span class="text-right text-xs tabular-nums">
								<span aria-hidden="true">{neighbour.label}</span>
								<span class="sr-only">{m.signal_similarity({ similarity: neighbour.label })}</span>
							</span>
						{/if}
					</li>
				{/each}
			</ol>
		{/if}
	{/if}
</div>
