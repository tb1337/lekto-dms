<script lang="ts">
	import Copy from '@lucide/svelte/icons/copy';
	import Download from '@lucide/svelte/icons/download';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { apiFetch } from '#lib/api/fetch.ts';
	import { apiError, ApiError } from '#lib/api/problem.ts';
	import Markdown from '#lib/components/document/Markdown.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// What was read from the document: the text as rendered Markdown, its source, and the
	// parser's structure (Docling's JSON). The text comes as soon as the document is parsed.
	let { documentId, filename }: { documentId: string; filename: string } = $props();

	type View = 'text' | 'markdown' | 'json';
	const PIECE = 20_000;
	// More than this is not shown; the download has all of it.
	const MOST_TEXT = 2_000_000;
	const MOST_JSON = 400_000;

	let view = $state<View>('text');
	let text = $state<string | null>(null);
	let total = $state(0);
	let structure = $state<string | null>(null);
	let structureBytes = $state(0);
	let problem = $state<string | null>(null);
	let loading = $state(true);
	let loadingStructure = $state(false);

	// An answer overtaken by a later request (several events at once) must not replace the
	// current text.
	let latest = 0;
	async function loadText() {
		const wanted = documentId;
		const request = ++latest;
		loading = true;
		try {
			let offset: number | null = 0;
			let collected = '';
			let length = 0;
			while (offset !== null && collected.length < MOST_TEXT) {
				const piece: { text: string; total_length: number; next_offset: number | null } =
					await unwrap(
						api.GET('/api/v1/documents/{id}/text', {
							params: { path: { id: wanted }, query: { offset, limit: PIECE } }
						})
					);
				collected += piece.text;
				length = piece.total_length;
				offset = piece.next_offset;
			}
			if (wanted !== documentId || request !== latest) return;
			text = collected;
			total = length;
			problem = null;
		} catch (error) {
			if (wanted !== documentId || request !== latest) return;
			// 409: not parsed yet; the next event brings the text.
			if (error instanceof ApiError && error.status === 409) text = null;
			else problem = describeError(error);
		} finally {
			if (request === latest) loading = false;
		}
	}

	async function loadStructure() {
		const wanted = documentId;
		loadingStructure = true;
		try {
			const answer = await apiFetch(
				new Request(new URL(`/api/v1/documents/${wanted}/structure`, location.origin))
			);
			if (answer.status === 409) {
				structure = null;
				return;
			}
			if (!answer.ok) throw await apiError(answer);
			const raw = await answer.text();
			if (wanted !== documentId) return;
			structureBytes = new Blob([raw]).size;
			structure =
				raw.length > MOST_JSON ? raw.slice(0, MOST_JSON) : JSON.stringify(JSON.parse(raw), null, 2);
		} catch (error) {
			if (wanted === documentId) problem = describeError(error);
		} finally {
			loadingStructure = false;
		}
	}

	$effect(() => {
		void documentId;
		untrack(() => {
			text = null;
			structure = null;
			problem = null;
		});
		void events.generation;
		void loadText();
		return events.subscribe((event) => {
			if (event.document_id === documentId && event.type === 'document.node_completed') {
				void loadText();
				if (structure !== null) void loadStructure();
			}
		});
	});

	$effect(() => {
		if (view === 'json' && structure === null) untrack(() => void loadStructure());
	});

	const shown = $derived(view === 'json' ? structure : text);
	const cut = $derived(view === 'json' && structureBytes > MOST_JSON);
	const stem = $derived(filename.replace(/\.[^.]+$/, '') || 'document');

	async function copy() {
		if (shown === null) return;
		try {
			await navigator.clipboard.writeText(shown);
			toast.success(m.content_copied());
		} catch (error) {
			toast.error(describeError(error));
		}
	}

	function download() {
		const link = window.document.createElement('a');
		if (view === 'json') {
			link.href = `/api/v1/documents/${documentId}/structure`;
			link.download = `${stem}.json`;
			link.click();
			return;
		}
		if (text === null) return;
		const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
		link.href = url;
		link.download = `${stem}.md`;
		link.click();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	}

	const views: { view: View; label: () => string }[] = [
		{ view: 'text', label: m.content_text },
		{ view: 'markdown', label: m.content_markdown },
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
				{#if structure !== null}
					{m.content_json_size({
						size: formatNumber(structureBytes / 1024, { maximumFractionDigits: 0 })
					})}
				{/if}
			{:else if text !== null}
				{m.text_length({ characters: formatNumber(total) })}
			{/if}
		</span>
		<div class="ml-auto flex gap-2">
			<Button variant="outline" disabled={shown === null} onclick={copy}>
				<Copy aria-hidden="true" />
				{m.content_copy()}
			</Button>
			<Button variant="outline" disabled={shown === null} onclick={download}>
				<Download aria-hidden="true" />
				{m.doc_download()}
			</Button>
		</div>
	</div>

	{#if cut}<p class="text-sm text-muted-foreground">{m.content_json_cut()}</p>{/if}

	<div class="h-[calc(100vh-17rem)] min-h-96 overflow-auto rounded-2xl border bg-card">
		{#if problem}
			<p class="p-6 text-destructive" role="alert">{problem}</p>
		{:else if shown === null}
			<p class="p-6 text-sm text-muted-foreground">
				{(view === 'json' ? loadingStructure : loading) ? m.loading() : m.text_none()}
			</p>
		{:else if view === 'text'}
			<article class="max-w-3xl px-9 py-7">
				<Markdown source={shown} />
			</article>
		{:else}
			<pre
				class="px-7 py-6 font-mono text-[13px] leading-relaxed {view === 'markdown'
					? 'whitespace-pre-wrap'
					: 'whitespace-pre'}">{shown}</pre>
		{/if}
	</div>
</section>
