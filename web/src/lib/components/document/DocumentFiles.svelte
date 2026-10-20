<script lang="ts">
	import Archive from '@lucide/svelte/icons/archive';
	import Copy from '@lucide/svelte/icons/copy';
	import FilePen from '@lucide/svelte/icons/file-pen';
	import FilePlus from '@lucide/svelte/icons/file-plus';
	import Inbox from '@lucide/svelte/icons/inbox';
	import Pencil from '@lucide/svelte/icons/pencil';
	import SearchIcon from '@lucide/svelte/icons/search';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import Segmented from '#lib/components/Segmented.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import {
		fingerprint,
		lifeOf,
		madeOn,
		madeWith,
		saidBy,
		type SaidKey,
		type StepKind
	} from '#lib/file-passport.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// The document's files as a passport (Tobi, 20.10.2026; not a table as in Paperless-ngx): the
	// life of the file from the sender to its last change in Lekto, one passport each for the
	// original and the archive (format, size beside the other's, a fingerprint of its SHA-256,
	// what made it, what it says about itself), and below every entry of their metadata, to
	// search and to narrow by file and source, in columns that keep their width.
	let { documentId }: { documentId: string } = $props();

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
		// The archive comes with the text recognition.
		return events.subscribe((event) => {
			if (event.document_id === documentId && event.type === 'document.node_completed') {
				void load();
			}
		});
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
		modified: { label: m.files_step_modified, icon: Pencil }
	};

	const life = $derived(files ? lifeOf(files) : []);
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

	/** A size as people read it: bytes, kB, MB (decimal, as file managers show them). */
	function size(bytes: number): string {
		const [value, unit] =
			bytes < 1000
				? [bytes, 'byte']
				: bytes < 1_000_000
					? [bytes / 1000, 'kilobyte']
					: [bytes / 1_000_000, 'megabyte'];
		return formatNumber(value, { style: 'unit', unit, maximumFractionDigits: 1 });
	}

	const when = (value: Date | string) =>
		formatDate(value, { dateStyle: 'medium', timeStyle: 'short' });

	/** What a file is, in a word: PDF, PDF/A-2B, JPEG. */
	function kind(file: Stored): string {
		const metadata = file.metadata;
		if (!metadata) return '';
		return metadata.pdfa ? `PDF/A-${metadata.pdfa}` : metadata.format;
	}

	function stepNote(step: StepKind): string {
		if (step === 'created' || step === 'changed') return m.files_step_sender();
		if (step === 'archived' && files?.archive)
			return m.files_step_as({ format: kind(files.archive) });
		return m.files_step_lekto();
	}

	function sizeNote(file: Stored, original: Stored): string {
		if (file === original) return m.files_original_note();
		const percent = Math.round((file.size / original.size - 1) * 100);
		if (percent === 0) return m.files_size_same();
		return percent > 0
			? m.files_size_more({ percent: formatNumber(percent) })
			: m.files_size_less({ percent: formatNumber(-percent) });
	}

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			toast.success(m.content_copied());
		} catch (error) {
			toast.error(describeError(error));
		}
	}
</script>

{#snippet passport(title: string, file: Stored, original: Stored, largest: number)}
	{@const metadata = file.metadata}
	{@const made = madeWith(metadata)}
	{@const dates = madeOn(metadata)}
	{@const said = saidBy(metadata)}
	{@const print = fingerprint(file.sha256)}
	<article
		aria-label={title}
		class="flex min-w-0 flex-col overflow-hidden rounded-2xl border bg-card"
	>
		<div class="flex items-center gap-3 px-4 pt-4 pb-3">
			<span
				class="grid h-14 w-11 shrink-0 place-items-end justify-center rounded-md border bg-surface pb-1.5 text-[10px] font-bold text-brand"
				aria-hidden="true">{metadata?.format ?? '?'}</span
			>
			<div class="flex min-w-0 flex-col gap-1">
				<h2 class="text-base font-semibold">{title}</h2>
				{#if metadata}
					<div class="flex flex-wrap gap-1.5">
						{#if metadata.pdf_version}
							<span
								class="rounded-full bg-secondary px-2 py-0.5 text-[11.5px] font-semibold text-muted-foreground"
							>
								{m.files_pdf_version({ version: metadata.pdf_version })}
							</span>
						{/if}
						{#if metadata.pdfa}
							<span
								class="rounded-full bg-lane-green px-2 py-0.5 text-[11.5px] font-semibold text-lane-green-foreground"
							>
								{kind(file)}
							</span>
						{/if}
						{#if metadata.width && metadata.height}
							<span
								class="rounded-full bg-secondary px-2 py-0.5 text-[11.5px] font-semibold text-muted-foreground"
							>
								{m.files_pixels_value({ width: metadata.width, height: metadata.height })}
							</span>
						{/if}
						{#if metadata.dpi}
							<span
								class="rounded-full bg-secondary px-2 py-0.5 text-[11.5px] font-semibold text-muted-foreground"
							>
								{m.files_dpi_value({ dpi: formatNumber(metadata.dpi) })}
							</span>
						{/if}
					</div>
				{/if}
			</div>
		</div>
		<dl class="grid grid-cols-3 border-y">
			<div class="flex flex-col gap-0.5 px-4 py-2.5">
				<dt class="order-last text-[11.5px] text-muted-foreground">{m.files_size()}</dt>
				<dd class="text-base font-semibold tabular-nums">{size(file.size)}</dd>
			</div>
			<div class="flex flex-col gap-0.5 border-l px-4 py-2.5">
				<dt class="order-last text-[11.5px] text-muted-foreground">{m.files_pages()}</dt>
				<dd class="text-base font-semibold tabular-nums">
					{metadata?.pages ? formatNumber(metadata.pages) : '–'}
				</dd>
			</div>
			<div class="flex flex-col gap-0.5 border-l px-4 py-2.5">
				<dt class="order-last text-[11.5px] text-muted-foreground">{m.files_entries()}</dt>
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
				<code class="font-mono text-[12.5px] break-all">
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
	</article>
{/snippet}

<!-- One card filling the view; inside, on its surface, the life, the passports and the entries. -->
<div
	class="flex min-h-[32rem] flex-col overflow-hidden rounded-2xl border bg-card lg:min-h-0 lg:flex-1"
>
	<!-- Positioned: what is only for screen readers stays inside the scrolling area. -->
	<div class="@container relative min-h-0 flex-1 overflow-y-auto bg-surface p-3.5">
		{#if problem}
			<p class="p-2 text-destructive" role="alert">{problem}</p>
		{:else if !files}
			<p class="p-2 text-sm text-muted-foreground">{m.loading()}</p>
		{:else}
			{@const largest = Math.max(files.original.size, files.archive?.size ?? 0, 1)}
			<div class="flex flex-col gap-3.5">
				<section aria-labelledby="files-life" class="rounded-2xl border bg-card p-4">
					<h2 id="files-life" class="text-[15px] font-semibold">{m.files_life()}</h2>
					<ol
						class="relative mt-4 grid gap-4 @3xl:[grid-template-columns:repeat(var(--steps),minmax(0,1fr))] @3xl:gap-0"
						style:--steps={life.length}
					>
						{#each life as step, index (step.kind)}
							{@const Icon = STEPS[step.kind].icon}
							<li
								class="relative flex items-start gap-3 @3xl:flex-col @3xl:items-center @3xl:gap-1.5 @3xl:px-2 @3xl:text-center"
							>
								{#if index > 0}
									<!-- The line from the step before, in the colour of where it happened. -->
									<span
										class={cn(
											'absolute top-3 right-1/2 hidden h-0.5 w-full @3xl:block',
											step.outside ? 'bg-muted-foreground/40' : 'bg-brand/50'
										)}
										aria-hidden="true"
									></span>
								{/if}
								<span
									class={cn(
										'relative z-10 grid size-6 shrink-0 place-items-center rounded-full border-2 bg-card',
										step.outside
											? 'border-muted-foreground/60 text-muted-foreground'
											: 'border-brand text-brand'
									)}
									aria-hidden="true"
								>
									<Icon class="size-3" />
								</span>
								<span class="flex min-w-0 flex-col gap-0.5 @3xl:items-center">
									<span class="text-sm font-semibold">{STEPS[step.kind].label()}</span>
									<time
										class="text-xs text-muted-foreground tabular-nums"
										datetime={step.at.toISOString()}
									>
										{when(step.at)}
									</time>
									<span class="text-xs text-muted-foreground">{stepNote(step.kind)}</span>
								</span>
							</li>
						{/each}
					</ol>
				</section>

				<div class="grid gap-3.5 @4xl:grid-cols-2">
					{@render passport(m.files_original(), files.original, files.original, largest)}
					{#if files.archive}
						{@render passport(m.files_archive(), files.archive, files.original, largest)}
					{:else}
						<section
							aria-label={m.files_archive()}
							class="flex flex-col gap-2 rounded-2xl border bg-card p-4"
						>
							<h2 class="text-base font-semibold">{m.files_archive()}</h2>
							<p class="text-sm text-muted-foreground">{m.files_no_archive()}</p>
						</section>
					{/if}
				</div>

				<section
					aria-labelledby="files-all"
					class="flex flex-col gap-3 rounded-2xl border bg-card p-4"
				>
					<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
						<h2 id="files-all" class="text-[15px] font-semibold">{m.files_all()}</h2>
						<!-- A width of its own: the controls beside it stay where they are. -->
						<span class="min-w-[7.5em] text-sm text-muted-foreground tabular-nums">
							{m.files_count({
								shown: formatNumber(entries.length),
								total: formatNumber(all.length)
							})}
						</span>
						<label
							class="flex h-10 min-w-0 flex-[1_1_14rem] items-center gap-2 rounded-full border border-input bg-card px-3.5 text-muted-foreground focus-within:border-ring dark:bg-input/30"
						>
							<SearchIcon class="size-4 shrink-0" aria-hidden="true" />
							<input
								type="search"
								bind:value={query}
								placeholder={m.files_search()}
								aria-label={m.files_search()}
								class="h-full min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm"
							/>
						</label>
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
							<table class="w-full min-w-[34rem] table-fixed border-collapse text-sm">
								<colgroup><col class="w-[30%]" /><col /><col class="w-28" /></colgroup>
								<thead>
									<tr
										class="text-left text-[11.5px] font-semibold tracking-wide text-muted-foreground uppercase"
									>
										<th class="px-2.5 pb-2 font-semibold">{m.files_key()}</th>
										<th class="px-2.5 pb-2 font-semibold">{m.files_value()}</th>
										<th class="px-2.5 pb-2 font-semibold">{m.files_source()}</th>
									</tr>
								</thead>
								<tbody>
									{#each entries as entry, index (index)}
										<tr class="border-t align-top">
											<td class="px-2.5 py-2 font-mono text-[12.5px] break-all">{entry.key}</td>
											<td class="px-2.5 py-2 break-words whitespace-pre-line">{entry.value}</td>
											<td class="px-2.5 py-2">
												<span
													class="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-muted-foreground"
												>
													{SOURCES[entry.source]()}
												</span>
											</td>
										</tr>
									{:else}
										<tr class="border-t">
											<td colspan="3" class="px-2.5 py-3 text-muted-foreground">
												{m.assignment_none_found()}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</section>
			</div>
		{/if}
	</div>
</div>
