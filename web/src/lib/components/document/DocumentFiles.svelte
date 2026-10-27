<script lang="ts">
	import Archive from '@lucide/svelte/icons/archive';
	import ClipboardCheck from '@lucide/svelte/icons/clipboard-check';
	import ClipboardClock from '@lucide/svelte/icons/clipboard-clock';
	import ClipboardMinus from '@lucide/svelte/icons/clipboard-minus';
	import Copy from '@lucide/svelte/icons/copy';
	import FilePen from '@lucide/svelte/icons/file-pen';
	import FilePlus from '@lucide/svelte/icons/file-plus';
	import Inbox from '@lucide/svelte/icons/inbox';
	import Pencil from '@lucide/svelte/icons/pencil';
	import { untrack } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { copyText } from '#lib/clipboard.ts';
	import Segmented from '#lib/components/Segmented.svelte';
	import ReceiptEdit from '#lib/components/document/ReceiptEdit.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { coalesced } from '#lib/coalesce.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import {
		fileKind,
		fileSize,
		fingerprint,
		gapOf,
		lifeOf,
		madeOn,
		madeWith,
		saidBy,
		type Reviewed,
		type SaidKey,
		type Step,
		type StepKind
	} from '#lib/file-passport.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import type { Tone } from '#lib/tones.ts';
	import SearchField from '#lib/components/SearchField.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';

	// The document's files as a passport (Tobi, 20.10.2026; not a table as in Paperless-ngx): the
	// life of the file from the sender to its last change in Lekto, one passport each for the
	// original and the archive (format, size beside the other's, a fingerprint of its SHA-256,
	// what made it, what it says about itself), and below every entry of their metadata, to
	// search and to narrow by file and source, in columns that keep their width. With the
	// document, the life ends with its review, and the line between two steps says how long
	// lay between them (Tobi, 21.10.2026); below the life, how its first processing ended, which
	// no later review changes (Tobi, 22.10.2026).
	// `editable`: when the document came in can be set at its milestone; `onchanged` follows.
	let {
		documentId,
		document,
		editable = false,
		onchanged
	}: {
		documentId: string;
		document?: Reviewed;
		editable?: boolean;
		onchanged?: () => void;
	} = $props();

	type Files = components['schemas']['DocumentFilesOut'];
	type Stored = components['schemas']['StoredFileOut'];
	type Source = components['schemas']['MetadataEntryOut']['source'];

	let files = $state<Files | null>(null);
	let problem = $state<string | null>(null);
	let which = $state('original');
	let source = $state('all');
	let query = $state('');

	let latest = 0;
	async function load() {
		const wanted = documentId;
		const request = ++latest;
		try {
			const read = await unwrap(
				api.GET('/api/v1/documents/{id}/files', { params: { path: { id: wanted } } })
			);
			if (wanted !== documentId || request !== latest) return;
			files = read;
			problem = null;
		} catch (error) {
			if (wanted === documentId && request === latest) problem = describeError(error);
		}
	}

	$effect(() => {
		void documentId;
		untrack(() => {
			files = null;
			problem = null;
		});
		void events.generation;
		void load();
		// The archive comes with the text recognition, the pages and the last change with other
		// nodes: loaded once after nodes that complete together (issue #75).
		const reload = coalesced(() => void load());
		const stop = events.subscribe((event) => {
			if (event.document_id === documentId && event.type === 'document.node_completed') {
				reload();
			}
		});
		return () => {
			stop();
			reload.cancel();
		};
	});

	const SOURCES: Record<Source, () => string> = {
		info: m.files_source_info,
		xmp: m.files_source_xmp,
		exif: m.files_source_exif
	};
	const SAID: Record<SaidKey, () => string> = {
		title: m.files_said_title,
		author: m.files_said_author,
		subject: m.files_said_subject,
		keywords: m.files_said_keywords,
		language: m.files_said_language
	};
	const STEPS: Record<StepKind, { label: () => string; icon: typeof Inbox }> = {
		created: { label: m.files_step_created, icon: FilePlus },
		changed: { label: m.files_step_changed, icon: FilePen },
		added: { label: m.files_step_added, icon: Inbox },
		archived: { label: m.files_step_archived, icon: Archive },
		confirmed: { label: m.files_step_confirmed, icon: ClipboardCheck },
		unreviewed: { label: m.files_step_unreviewed, icon: ClipboardMinus },
		modified: { label: m.files_step_modified, icon: Pencil },
		review: { label: m.files_step_confirmed, icon: ClipboardClock }
	};

	type FirstLane = NonNullable<Reviewed['first_lane']>;
	const FIRST_LANES: Record<FirstLane, { label: () => string; tone: Tone }> = {
		green: { label: m.files_first_lane_green, tone: 'green' },
		yellow: { label: m.files_first_lane_yellow, tone: 'yellow' },
		red: { label: m.files_first_lane_red, tone: 'red' }
	};

	const life = $derived(files ? lifeOf(files, document) : []);
	// A review still to come in the colour of the lane that waits for it.
	const red = $derived(document?.lane === 'red');
	const shown = $derived(
		files ? (which === 'archive' && files.archive ? files.archive : files.original) : null
	);
	// The sources either file has, the same for both: switching keeps the controls in place.
	const sources = $derived(
		(['info', 'xmp', 'exif'] as const).filter((kind) =>
			[files?.original, files?.archive].some((file) =>
				file?.metadata?.entries.some((entry) => entry.source === kind)
			)
		)
	);
	const all = $derived(shown?.metadata?.entries ?? []);
	const entries = $derived.by(() => {
		const wanted = query.trim().toLocaleLowerCase();
		return all.filter(
			(entry) =>
				(source === 'all' || entry.source === source) &&
				(wanted === '' || `${entry.key} ${entry.value}`.toLocaleLowerCase().includes(wanted))
		);
	});

	const when = (value: Date | string) =>
		formatDate(value, { dateStyle: 'medium', timeStyle: 'short' });

	function stepNote(step: Step): string {
		if (step.kind === 'created' || step.kind === 'changed') return m.files_step_sender();
		if (step.kind === 'archived' && files?.archive)
			return m.files_step_as({ format: fileKind(files.archive) });
		if (step.kind === 'confirmed')
			return step.takenOver ? m.files_step_taken_over() : m.files_step_by_hand();
		if (step.kind === 'added' && document?.channel === 'migration')
			return m.files_step_taken_over();
		if (step.kind === 'unreviewed') return m.files_step_pipeline();
		if (step.kind === 'review' && files)
			return m.files_step_since({ date: formatDate(files.added, { dateStyle: 'medium' }) });
		return m.files_step_lekto();
	}

	/** How long lay between two steps: 5 minutes, 2 days, 1 year. */
	function duration(gap: NonNullable<ReturnType<typeof gapOf>>): string {
		return formatNumber(gap.value, { style: 'unit', unit: gap.unit, unitDisplay: 'long' });
	}

	function sizeNote(file: Stored, original: Stored): string {
		if (file === original) return m.files_original_note();
		const percent = Math.round((file.size / original.size - 1) * 100);
		if (percent === 0) return m.files_size_same();
		return percent > 0
			? m.files_size_more({ percent: formatNumber(percent) })
			: m.files_size_less({ percent: formatNumber(-percent) });
	}

	const copy = (text: string) => copyText(text);
</script>

{#snippet passport(title: string, file: Stored, original: Stored, largest: number)}
	{@const metadata = file.metadata}
	{@const made = madeWith(metadata)}
	{@const dates = madeOn(metadata)}
	{@const said = saidBy(metadata)}
	{@const print = fingerprint(file.sha256)}
	<Card.Root
		as="article"
		size="flush"
		aria-label={title}
		class="flex min-w-0 flex-col overflow-hidden"
	>
		<div class="flex items-center gap-3 px-4 pt-4 pb-3">
			<span
				class="grid h-14 w-11 shrink-0 place-items-end justify-center rounded-md border bg-surface pb-1.5 text-nano font-bold text-brand"
				aria-hidden="true">{metadata?.format ?? '?'}</span
			>
			<div class="flex min-w-0 flex-col gap-1">
				<SectionTitle size="card">{title}</SectionTitle>
				{#if metadata}
					<div class="flex flex-wrap gap-1.5">
						{#if metadata.pdf_version}
							<Badge variant="muted">
								{m.files_pdf_version({ version: metadata.pdf_version })}
							</Badge>
						{/if}
						{#if metadata.pdfa}
							<Badge variant="green">
								{fileKind(file)}
							</Badge>
						{/if}
						{#if metadata.width && metadata.height}
							<Badge variant="muted">
								{m.files_pixels_value({ width: metadata.width, height: metadata.height })}
							</Badge>
						{/if}
						{#if metadata.dpi}
							<Badge variant="muted">
								{m.files_dpi_value({ dpi: formatNumber(metadata.dpi) })}
							</Badge>
						{/if}
					</div>
				{/if}
			</div>
		</div>
		<dl class="grid grid-cols-3 border-y">
			<div class="flex flex-col gap-0.5 px-4 py-2.5">
				<dt class="order-last text-xs text-muted-foreground">{m.files_size()}</dt>
				<dd class="text-base font-semibold tabular-nums">{fileSize(file.size)}</dd>
			</div>
			<div class="flex flex-col gap-0.5 border-l px-4 py-2.5">
				<dt class="order-last text-xs text-muted-foreground">{m.files_pages()}</dt>
				<dd class="text-base font-semibold tabular-nums">
					{metadata?.pages ? formatNumber(metadata.pages) : '–'}
				</dd>
			</div>
			<div class="flex flex-col gap-0.5 border-l px-4 py-2.5">
				<dt class="order-last text-xs text-muted-foreground">{m.files_entries()}</dt>
				<dd class="text-base font-semibold tabular-nums">
					{metadata ? formatNumber(metadata.entries.length) : '–'}
				</dd>
			</div>
		</dl>
		<div class="mx-4 mt-3 h-1.5 overflow-hidden rounded-full bg-secondary" aria-hidden="true">
			<div class="h-full rounded-full bg-brand" style:width="{(file.size / largest) * 100}%"></div>
		</div>
		<p class="mx-4 mt-1.5 text-xs text-muted-foreground">{sizeNote(file, original)}</p>
		<div class="flex items-center gap-3.5 px-4 py-3.5">
			<svg
				viewBox="0 0 8 8"
				class="size-16 shrink-0 rounded-lg bg-surface"
				shape-rendering="crispEdges"
				role="img"
				aria-label={m.files_fingerprint()}
			>
				{#each print.cells as cell, index (index)}
					<rect
						x={cell.x}
						y={cell.y}
						width="1"
						height="1"
						fill="hsl({(print.hue + cell.shade * 24) % 360} 55% {42 + cell.shade * 6}%)"
					/>
				{/each}
			</svg>
			<div class="flex min-w-0 flex-col gap-1">
				<span class="text-xs text-muted-foreground">{m.files_fingerprint()}</span>
				<code class="font-mono text-meta break-all">
					{file.sha256.slice(0, 16)}…{file.sha256.slice(-8)}
				</code>
				<Button
					variant="ghost"
					size="sm"
					class="-ml-2 h-7 w-fit px-2"
					onclick={() => copy(file.sha256)}
				>
					<Copy aria-hidden="true" />
					{m.files_copy_hash()}
				</Button>
			</div>
		</div>
		{#if !metadata}
			<p class="mx-4 mb-4 text-sm text-muted-foreground">{m.files_unreadable()}</p>
		{:else}
			{#if made.creator || made.producer || made.camera}
				<div class="mx-4 mb-3 flex flex-col gap-0.5 rounded-xl bg-surface px-3 py-2.5 text-sm">
					{#if made.camera}
						<span class="text-xs text-muted-foreground">{m.files_camera()}</span>
						<span class="font-medium break-words">{made.camera}</span>
					{/if}
					{#if made.creator}
						<span class="text-xs text-muted-foreground">{m.files_made_with()}</span>
						<span class="font-medium break-words">{made.creator}</span>
					{/if}
					{#if made.producer}
						<span class="text-xs text-muted-foreground">
							{made.creator ? m.files_converted_with() : m.files_made_with()}
						</span>
						<span class="font-medium break-words">{made.producer}</span>
					{/if}
				</div>
			{/if}
			{#if said.length > 0 || dates.created || dates.changed}
				<dl class="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 px-4 pb-4 text-sm">
					{#each said as [key, value] (key)}
						<dt class="text-muted-foreground">{SAID[key]()}</dt>
						<dd class="break-words">{value}</dd>
					{/each}
					{#if dates.created}
						<dt class="text-muted-foreground">{m.files_step_created()}</dt>
						<dd>{when(dates.created)}</dd>
					{/if}
					{#if dates.changed}
						<dt class="text-muted-foreground">{m.files_step_changed()}</dt>
						<dd>{when(dates.changed)}</dd>
					{/if}
				</dl>
			{/if}
		{/if}
	</Card.Root>
{/snippet}

<!-- One card filling the view; inside, on its surface, the life, the passports and the entries. -->
<Card.Root size="flush" class="flex min-h-[32rem] flex-col overflow-hidden lg:min-h-0 lg:flex-1">
	<!-- Positioned: what is only for screen readers stays inside the scrolling area. -->
	<div class="@container relative min-h-0 flex-1 overflow-y-auto bg-surface p-3.5">
		{#if problem}
			<div class="p-2"><LoadProblem {problem} onretry={load} /></div>
		{:else if !files}
			<Loading class="p-2 text-sm" />
		{:else}
			{@const largest = Math.max(files.original.size, files.archive?.size ?? 0, 1)}
			<div class="flex flex-col gap-3.5">
				<Card.Root as="section" size="row" aria-labelledby="files-life">
					<SectionTitle size="card" id="files-life">{m.files_life()}</SectionTitle>
					<ol
						class="relative mt-4 grid gap-4 @3xl:[grid-template-columns:repeat(var(--steps),minmax(0,1fr))] @3xl:gap-0"
						style:--steps={life.length}
					>
						{#each life as step, index (step.kind)}
							{@const Icon = STEPS[step.kind].icon}
							{@const gap = index > 0 ? gapOf(life[index - 1].at, step.at) : null}
							{@const grey = step.outside || step.kind === 'unreviewed'}
							<li
								class="relative flex items-start gap-3 @3xl:flex-col @3xl:items-center @3xl:gap-1.5 @3xl:px-2 @3xl:text-center"
							>
								{#if index > 0}
									<!-- The line from the step before, in the colour of where it happened;
									     dashed to a review still to come. -->
									<span
										class={cn(
											'absolute top-3 right-1/2 hidden w-full @3xl:block',
											step.open
												? cn(
														'h-0 border-t-2 border-dashed',
														red
															? 'border-lane-red-foreground/60'
															: 'border-lane-yellow-foreground/60'
													)
												: grey
													? 'h-0.5 bg-muted-foreground/40'
													: 'h-0.5 bg-brand/50'
										)}
										aria-hidden="true"
									></span>
									{#if gap}
										<!-- How long lay between the two, on the line where they meet. -->
										<span
											class="absolute top-3 left-0 z-10 hidden -translate-x-1/2 -translate-y-1/2 rounded-full bg-card px-1.5 text-micro leading-4 whitespace-nowrap text-muted-foreground tabular-nums @3xl:block"
											aria-hidden="true"
										>
											{duration(gap)}
										</span>
									{/if}
								{/if}
								<span
									class={cn(
										'relative z-10 grid size-6 shrink-0 place-items-center rounded-full border-2 bg-card',
										step.open
											? cn(
													'border-dashed',
													red
														? 'border-lane-red-foreground text-lane-red-foreground'
														: 'border-lane-yellow-foreground text-lane-yellow-foreground'
												)
											: grey
												? 'border-muted-foreground/60 text-muted-foreground'
												: 'border-brand text-brand'
									)}
									aria-hidden="true"
								>
									<Icon class="size-3" />
								</span>
								<span class="flex min-w-0 flex-col gap-0.5 @3xl:items-center">
									<span class="text-sm font-semibold">{STEPS[step.kind].label()}</span>
									{#if step.open}
										<span
											class={cn(
												'text-xs font-medium',
												red ? 'text-lane-red-foreground' : 'text-lane-yellow-foreground'
											)}
										>
											{m.files_step_pending()}
										</span>
									{:else}
										<span class="flex items-center gap-1">
											<time
												class="text-xs text-muted-foreground tabular-nums"
												datetime={step.at.toISOString()}
											>
												{when(step.at)}
											</time>
											{#if step.kind === 'added' && editable}
												<ReceiptEdit
													{documentId}
													value={files.added}
													onchanged={() => {
														void load();
														onchanged?.();
													}}
												/>
											{/if}
										</span>
									{/if}
									<span class="text-xs text-muted-foreground">{stepNote(step)}</span>
									{#if gap && !step.open}
										<!-- On the line where there is one; below it a line of its own (a review
										     to come says since when instead). -->
										<span class="text-xs text-muted-foreground @3xl:sr-only">
											{m.files_gap_after({ duration: duration(gap) })}
										</span>
									{/if}
								</span>
							</li>
						{/each}
					</ol>
					{#if document?.first_lane}
						{@const first = FIRST_LANES[document.first_lane]}
						<dl class="mt-4 flex flex-wrap items-center gap-x-2.5 gap-y-1 border-t pt-3 text-sm">
							<dt class="text-muted-foreground">{m.files_first_lane()}</dt>
							<dd><Badge variant={first.tone}>{first.label()}</Badge></dd>
						</dl>
					{/if}
				</Card.Root>

				<div class="grid gap-3.5 @4xl:grid-cols-2">
					{@render passport(m.files_original(), files.original, files.original, largest)}
					{#if files.archive}
						{@render passport(m.files_archive(), files.archive, files.original, largest)}
					{:else}
						<Card.Root
							as="section"
							size="row"
							aria-label={m.files_archive()}
							class="flex flex-col gap-2"
						>
							<SectionTitle size="card">{m.files_archive()}</SectionTitle>
							<p class="text-sm text-muted-foreground">{m.files_no_archive()}</p>
						</Card.Root>
					{/if}
				</div>

				<Card.Root as="section" size="row" aria-labelledby="files-all" class="flex flex-col gap-3">
					<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
						<SectionTitle size="card" id="files-all">{m.files_all()}</SectionTitle>
						<!-- A width of its own: the controls beside it stay where they are. -->
						<span class="min-w-[7.5em] text-sm text-muted-foreground tabular-nums">
							{m.files_count({
								shown: formatNumber(entries.length),
								total: formatNumber(all.length)
							})}
						</span>
						<SearchField bind:value={query} label={m.files_search()} class="flex-[1_1_14rem]" />
						{#if files.archive}
							<Segmented
								bind:value={which}
								label={m.files_which()}
								options={[
									{ value: 'original', label: m.files_original() },
									{ value: 'archive', label: m.files_archive() }
								]}
							/>
						{/if}
						{#if sources.length > 1}
							<Segmented
								bind:value={source}
								label={m.files_source()}
								options={[
									{ value: 'all', label: m.files_source_all() },
									...sources.map((kind) => ({ value: kind, label: SOURCES[kind]() }))
								]}
							/>
						{/if}
					</div>
					{#if !shown?.metadata}
						<p class="text-sm text-muted-foreground">{m.files_unreadable()}</p>
					{:else if all.length === 0}
						<p class="text-sm text-muted-foreground">{m.files_metadata_none()}</p>
					{:else}
						<div class="overflow-x-auto">
							<Table.Root class="w-full min-w-[34rem] table-fixed border-collapse text-sm">
								<colgroup><col class="w-[30%]" /><col /><col class="w-28" /></colgroup>
								<Table.Header>
									<Table.Row>
										<Table.Head class="px-2.5">{m.files_key()}</Table.Head>
										<Table.Head class="px-2.5">{m.files_value()}</Table.Head>
										<Table.Head class="px-2.5">{m.files_source()}</Table.Head>
									</Table.Row>
								</Table.Header>
								<Table.Body>
									{#each entries as entry, index (index)}
										<Table.Row class="border-t align-top">
											<Table.Cell class="px-2.5 py-2 font-mono text-meta break-all"
												>{entry.key}</Table.Cell
											>
											<Table.Cell class="px-2.5 py-2 break-words whitespace-pre-line"
												>{entry.value}</Table.Cell
											>
											<Table.Cell class="px-2.5 py-2">
												<Badge variant="muted">
													{SOURCES[entry.source]()}
												</Badge>
											</Table.Cell>
										</Table.Row>
									{:else}
										<Table.Row class="border-t">
											<Table.Cell colspan={3} class="px-2.5 py-3 text-muted-foreground">
												{m.assignment_none_found()}
											</Table.Cell>
										</Table.Row>
									{/each}
								</Table.Body>
							</Table.Root>
						</div>
					{/if}
				</Card.Root>
			</div>
		{/if}
	</div>
</Card.Root>
