<script lang="ts">
	import Copy from '@lucide/svelte/icons/copy';
	import Download from '@lucide/svelte/icons/download';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { apiFetch } from '#lib/api/fetch.ts';
	import { apiError, ApiError } from '#lib/api/problem.ts';
	import JsonTree from '#lib/components/document/JsonTree.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// What was read from the document: the text as it is set, in a fixed-pitch font so that its
	// columns line up, page by page, and its structure (pages, lines and words with boxes). The
	// text comes as soon as the document is parsed. A document parsed before 0.2 shows Docling's
	// Markdown as it is until it is read again.
	let { documentId, filename }: { documentId: string; filename: string } = $props();

	type View = 'text' | 'json';
	const PIECE = 20_000;
	// More than this is not shown (the download has all of it).
	const MOST_TEXT = 2_000_000;
	const MOST_JSON = 50_000_000;

	let view = $state<View>('text');
	let text = $state<string | null>(null);
	let total = $state(0);
	let textProblem = $state<string | null>(null);
	let loading = $state(true);
	// The parsed structure; `undefined` until it is there. Too large ones are only downloaded.
	let structure = $state<unknown>(undefined);
	let structureBytes = $state(0);
	let structureTooLarge = $state(false);
	let structureProblem = $state<string | null>(null);
	let loadingStructure = $state(false);

	type Piece = { text: string; total_length: number; next_offset: number | null };

	/** The text from `offset` on, up to `most` characters; with the total length. */
	async function readText(id: string, most: number): Promise<{ text: string; total: number }> {
		let offset: number | null = 0;
		let collected = '';
		let length = 0;
		while (offset !== null && collected.length < most) {
			const piece: Piece = await unwrap(
				api.GET('/api/v1/documents/{id}/text', {
					params: { path: { id }, query: { offset, limit: PIECE } }
				})
			);
			collected += piece.text;
			length = piece.total_length;
			offset = piece.next_offset;
		}
		return { text: collected, total: length };
	}

	// An answer overtaken by a later request (several events at once) must not replace the
	// current text or structure.
	let latest = 0;
	async function loadText() {
		const wanted = documentId;
		const request = ++latest;
		loading = true;
		try {
			const read = await readText(wanted, MOST_TEXT);
			if (wanted !== documentId || request !== latest) return;
			text = read.text;
			total = read.total;
			textProblem = null;
		} catch (error) {
			if (wanted !== documentId || request !== latest) return;
			// 409: not parsed yet; the next event brings the text.
			if (error instanceof ApiError && error.status === 409) text = null;
			else textProblem = describeError(error);
		} finally {
			if (request === latest) loading = false;
		}
	}

	let latestStructure = 0;
	async function loadStructure() {
		const wanted = documentId;
		const request = ++latestStructure;
		loadingStructure = true;
		try {
			const answer = await apiFetch(
				new Request(new URL(`/api/v1/documents/${wanted}/structure`, location.origin))
			);
			if (wanted !== documentId || request !== latestStructure) return;
			if (answer.status === 409) {
				structure = undefined;
				return;
			}
			if (!answer.ok) throw await apiError(answer);
			const raw = await answer.text();
			if (wanted !== documentId || request !== latestStructure) return;
			structureBytes = new Blob([raw]).size;
			structureTooLarge = raw.length > MOST_JSON;
			structure = structureTooLarge ? null : JSON.parse(raw);
			structureProblem = null;
		} catch (error) {
			if (wanted === documentId && request === latestStructure) {
				structureProblem = describeError(error);
			}
		} finally {
			if (request === latestStructure) loadingStructure = false;
		}
	}

	$effect(() => {
		void documentId;
		untrack(() => {
			text = null;
			structure = undefined;
			structureTooLarge = false;
			textProblem = null;
			structureProblem = null;
		});
		void events.generation;
		void loadText();
		return events.subscribe((event) => {
			if (event.document_id === documentId && event.type === 'document.node_completed') {
				void loadText();
				if (structure !== undefined) void loadStructure();
			}
		});
	});

	$effect(() => {
		if (view === 'json' && structure === undefined && structureProblem === null) {
			untrack(() => void loadStructure());
		}
	});

	const ready = $derived(view === 'json' ? structure !== undefined : text !== null);
	// The pages of the text: a form feed on a line of its own separates them.
	const pages = $derived((text ?? '').split(/\n?\f\n?/));
	const problem = $derived(view === 'json' ? structureProblem : textProblem);
	const stem = $derived(filename.replace(/\.[^.]+$/, '') || 'document');

	async function copy() {
		if (!ready) return;
		try {
			// The structure as text only when asked for: it can be large.
			await navigator.clipboard.writeText(
				view === 'json' ? JSON.stringify(structure, null, 2) : (text ?? '')
			);
			toast.success(m.content_copied());
		} catch (error) {
			toast.error(describeError(error));
		}
	}

	async function download() {
		const link = window.document.createElement('a');
		if (view === 'json') {
			link.href = `/api/v1/documents/${documentId}/structure`;
			link.download = `${stem}.json`;
			link.click();
			return;
		}
		if (text === null) return;
		let whole = text;
		if (text.length < total) {
			// What is shown stops short; the file has all of it.
			try {
				whole = (await readText(documentId, Infinity)).text;
			} catch (error) {
				toast.error(describeError(error));
				return;
			}
		}
		const url = URL.createObjectURL(new Blob([whole], { type: 'text/plain;charset=utf-8' }));
		link.href = url;
		link.download = `${stem}.txt`;
		link.click();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}

	const views: { view: View; label: () => string }[] = [
		{ view: 'text', label: m.content_text },
		{ view: 'json', label: m.content_json }
	];
</script>

<section class="flex flex-col gap-3" aria-label={m.tab_content()}>
	<div class="flex flex-wrap items-center gap-3">
		<div
			role="group"
			aria-label={m.content_view()}
			class="flex gap-0.5 rounded-xl border bg-card p-[3px]"
		>
			{#each views as entry (entry.view)}
				<button
					type="button"
					aria-pressed={view === entry.view}
					onclick={() => (view = entry.view)}
					class={cn(
						'h-[34px] rounded-[10px] px-3.5 text-sm transition-colors',
						view === entry.view
							? 'bg-primary font-medium text-primary-foreground'
							: 'text-muted-foreground hover:text-foreground'
					)}
				>
					{entry.label()}
				</button>
			{/each}
		</div>
		<span class="text-sm text-muted-foreground">
			{#if view === 'json'}
				{#if structure !== undefined}
					{m.content_json_size({
						size: formatNumber(structureBytes / 1024, { maximumFractionDigits: 0 })
					})}
				{/if}
			{:else if text !== null}
				{m.text_length({ characters: formatNumber(total) })}
			{/if}
		</span>
		<div class="ml-auto flex gap-2">
			<Button variant="outline" disabled={!ready || structureTooLarge} onclick={copy}>
				<Copy aria-hidden="true" />
				{m.content_copy()}
			</Button>
			<Button variant="outline" disabled={!ready} onclick={download}>
				<Download aria-hidden="true" />
				{m.doc_download()}
			</Button>
		</div>
	</div>

	<div class="h-[calc(100vh-17rem)] min-h-96 overflow-auto rounded-2xl border bg-card">
		{#if problem}
			<p class="p-6 text-destructive" role="alert">{problem}</p>
		{:else if !ready}
			<p class="p-6 text-sm text-muted-foreground">
				{(view === 'json' ? loadingStructure : loading) ? m.loading() : m.text_none()}
			</p>
		{:else if view === 'text'}
			<!-- As set: no wrapping, the box scrolls sideways. -->
			{#each pages as page, index (index)}
				<section aria-label={m.content_page({ page: index + 1 })} class="px-7 py-6">
					{#if pages.length > 1}
						<p class="mb-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
							{m.content_page({ page: index + 1 })}
						</p>
					{/if}
					<pre class="font-mono text-[13px] leading-relaxed whitespace-pre">{page}</pre>
				</section>
				{#if index < pages.length - 1}<hr class="border-muted" />{/if}
			{/each}
		{:else if structureTooLarge}
			<p class="p-6 text-sm text-muted-foreground">{m.content_json_too_large()}</p>
		{:else}
			<div class="px-5 py-5 font-mono text-[13px] leading-relaxed">
				<JsonTree value={structure} />
			</div>
		{/if}
	</div>
</section>
