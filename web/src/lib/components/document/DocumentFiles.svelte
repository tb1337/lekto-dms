<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Copy from '@lucide/svelte/icons/copy';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The document's files as they are stored, as Paperless-ngx shows them: when it was added and
	// changed, its original's name and type, and for the original and the archive their size,
	// SHA-256 and what they say about themselves (a PDF's information and XMP, an image's EXIF).
	let { documentId }: { documentId: string } = $props();

	type Files = components['schemas']['DocumentFilesOut'];
	type Stored = components['schemas']['StoredFileOut'];
	type Source = components['schemas']['MetadataEntryOut']['source'];

	let files = $state<Files | null>(null);
	let problem = $state<string | null>(null);

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

	const when = (value: string) => formatDate(value, { dateStyle: 'medium', timeStyle: 'short' });

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			toast.success(m.content_copied());
		} catch (error) {
			toast.error(describeError(error));
		}
	}
</script>

{#snippet row(label: string, value: string, mono = false)}
	<dt class="text-muted-foreground">{label}</dt>
	<dd class={mono ? 'font-mono text-[13px] break-words' : 'break-words'}>{value}</dd>
{/snippet}

{#snippet stored(title: string, metadataTitle: string, file: Stored)}
	{@const metadata = file.metadata}
	<section aria-label={title} class="flex min-w-0 flex-col gap-3 rounded-2xl border bg-card p-4">
		<h2 class="text-[15px] font-semibold">{title}</h2>
		<dl
			class="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]"
		>
			{@render row(m.files_size(), size(file.size))}
			<dt class="text-muted-foreground">{m.files_sha256()}</dt>
			<dd class="flex items-start gap-1">
				<span class="min-w-0 flex-1 font-mono text-[13px] break-all">{file.sha256}</span>
				<Button
					variant="ghost"
					size="icon"
					class="-my-1 size-7 shrink-0"
					aria-label={m.files_copy_hash()}
					onclick={() => copy(file.sha256)}
				>
					<Copy aria-hidden="true" />
				</Button>
			</dd>
			{#if metadata}
				{@render row(m.files_format(), metadata.format)}
				{#if metadata.pdf_version}{@render row(m.files_pdf_version(), metadata.pdf_version)}{/if}
				{#if metadata.pdfa}{@render row(m.files_pdfa(), metadata.pdfa)}{/if}
				{#if metadata.width && metadata.height}
					{@render row(
						m.files_pixels(),
						m.files_pixels_value({ width: metadata.width, height: metadata.height })
					)}
				{/if}
				{#if metadata.dpi}
					{@render row(m.files_dpi(), m.files_dpi_value({ dpi: formatNumber(metadata.dpi) }))}
				{/if}
				{#if metadata.pages}{@render row(m.files_pages(), formatNumber(metadata.pages))}{/if}
			{/if}
		</dl>
		{#if !metadata}
			<p class="text-sm text-muted-foreground">{m.files_unreadable()}</p>
		{:else}
			<details class="group rounded-xl border bg-surface" open>
				<summary
					class="flex cursor-pointer list-none items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium [&::-webkit-details-marker]:hidden"
				>
					<ChevronDown
						class="size-4 shrink-0 -rotate-90 transition-transform group-open:rotate-0"
						aria-hidden="true"
					/>
					{metadataTitle}
					<span class="text-xs font-normal text-muted-foreground">
						{formatNumber(metadata.entries.length)}
					</span>
				</summary>
				{#if metadata.entries.length === 0}
					<p class="px-3 pb-3 text-sm text-muted-foreground">{m.files_metadata_none()}</p>
				{:else}
					<dl
						class="grid grid-cols-[minmax(0,1fr)] gap-x-4 gap-y-2 px-3 pb-3 text-sm sm:grid-cols-[minmax(8rem,14rem)_minmax(0,1fr)]"
					>
						{#each metadata.entries as entry, index (index)}
							<dt class="flex min-w-0 items-baseline gap-1.5">
								<span class="font-mono text-[13px] break-all">{entry.key}</span>
								<span class="sr-only">({SOURCES[entry.source]()})</span>
								{#if entry.source !== 'xmp'}
									<span
										class="shrink-0 rounded-full bg-secondary px-1.5 text-[10px] leading-4 text-muted-foreground"
										aria-hidden="true">{SOURCES[entry.source]()}</span
									>
								{/if}
							</dt>
							<dd class="min-w-0 break-words whitespace-pre-line">{entry.value}</dd>
						{/each}
					</dl>
				{/if}
			</details>
		{/if}
	</section>
{/snippet}

<!-- One card filling the view; inside, on its surface, the file and its two stored forms. -->
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
			<div class="grid gap-3.5 @4xl:grid-cols-2">
				<section
					aria-label={m.files_title()}
					class="flex flex-col gap-3 rounded-2xl border bg-card p-4 @4xl:col-span-2"
				>
					<h2 class="text-[15px] font-semibold">{m.files_title()}</h2>
					<dl
						class="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]"
					>
						{@render row(m.files_added(), when(files.added))}
						{@render row(m.files_modified(), when(files.modified))}
						{@render row(m.files_original_filename(), files.original_filename)}
						{@render row(m.files_media_type(), files.media_type, true)}
						{#if files.page_count}{@render row(
								m.files_pages(),
								formatNumber(files.page_count)
							)}{/if}
					</dl>
				</section>
				{@render stored(m.files_original(), m.files_metadata_original(), files.original)}
				{#if files.archive}
					{@render stored(m.files_archive(), m.files_metadata_archive(), files.archive)}
				{:else}
					<section
						aria-label={m.files_archive()}
						class="flex flex-col gap-2 rounded-2xl border bg-card p-4"
					>
						<h2 class="text-[15px] font-semibold">{m.files_archive()}</h2>
						<p class="text-sm text-muted-foreground">{m.files_no_archive()}</p>
					</section>
				{/if}
			</div>
		{/if}
	</div>
</div>
