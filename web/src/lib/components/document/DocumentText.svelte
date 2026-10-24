<script lang="ts">
	import Copy from '@lucide/svelte/icons/copy';
	import { tick, untrack, type Snippet } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import { copyText } from '#lib/clipboard.ts';
	import PaneHead from '#lib/components/document/PaneHead.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { inUnits, pageRanges, quoteStretches, segmentsOf, type Stretch } from '#lib/facts.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// What was read from the document: the text as it is set, in a fixed-pitch font so that its
	// columns line up, page by page; `marks` (what a fact points to) and `quotes` (those of the
	// fields) marked in it.
	// The text comes as soon as the document is parsed. A document parsed before 0.2 shows
	// Docling's Markdown as it is until it is read again.
	let {
		documentId,
		vision = false,
		hasText = true,
		marks = [],
		quotes = [],
		end,
		onpage
	}: {
		documentId: string;
		/** The vision language model read the text (a person asked for it). */
		vision?: boolean;
		/** The document has its text: before, nothing is asked for (409). */
		hasText?: boolean;
		/** Spans in characters of the whole text. */
		marks?: readonly Stretch[];
		/** Passages to find in the text and mark there. */
		quotes?: readonly string[];
		/** At the end of the head: the pane's switch. */
		end?: Snippet;
		/** The page in the upper third of what is seen of the text, and how many there are. */
		onpage?: (current: number, total: number) => void;
	} = $props();

	// More than this is not shown (copying takes all of it).
	const MOST_TEXT = 2_000_000;

	let textBox = $state<HTMLDivElement | null>(null);
	let text = $state<string | null>(null);
	let total = $state(0);
	let problem = $state<string | null>(null);
	let loading = $state(true);

	type Piece = { text: string; total_length: number; next_offset: number | null };

	/** The text from the start, up to `most` characters, in pieces as large as the API gives
	 * them; with the total length. */
	async function readText(id: string, most: number): Promise<{ text: string; total: number }> {
		let offset: number | null = 0;
		let collected = '';
		let length = 0;
		while (offset !== null && collected.length < most) {
			const piece: Piece = await unwrap(
				api.GET('/api/v1/documents/{id}/text', {
					params: { path: { id }, query: { offset } }
				})
			);
			collected += piece.text;
			length = piece.total_length;
			offset = piece.next_offset;
		}
		return { text: collected, total: length };
	}

	// An answer overtaken by a later request (several events at once) must not replace the
	// current text.
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

	$effect(() => {
		void documentId;
		untrack(() => {
			text = null;
			problem = null;
		});
		if (!hasText) {
			loading = false;
			return;
		}
		void events.generation;
		void loadText();
		// The text is read by its node alone (issue #75).
		return events.subscribe((event) => {
			if (
				event.document_id === documentId &&
				event.type === 'document.node_completed' &&
				event.node === 'parse'
			) {
				void loadText();
			}
		});
	});

	// The pages of the text: a form feed on a line of its own separates them.
	const pages = $derived((text ?? '').split(/\n?\f\n?/));
	const ranges = $derived(pageRanges(text ?? ''));
	const marked = $derived.by(() => {
		if (text === null) return [];
		const whole = text;
		return [...inUnits(whole, marks), ...quotes.flatMap((quote) => quoteStretches(whole, quote))];
	});

	// The page in the upper third of what is seen of the text, as the pages' viewer counts: the
	// text scrolls itself on a wide screen, with the window on a narrow one.
	let current = $state(1);
	function follow() {
		if (!textBox) return;
		const box = textBox.getBoundingClientRect();
		const top = Math.max(box.top, 0);
		const line = top + (Math.min(box.bottom, window.innerHeight) - top) / 3;
		let at = 1;
		for (const section of textBox.querySelectorAll<HTMLElement>('[data-page]')) {
			if (section.getBoundingClientRect().top > line) break;
			at = Number(section.dataset.page);
		}
		current = at;
	}
	$effect(() => {
		void pages;
		void tick().then(follow);
	});
	$effect(() => onpage?.(current, text === null ? 0 : pages.length));

	/** Scroll the first mark into view, once it is drawn. */
	export async function revealMark() {
		await tick();
		textBox?.querySelector('[data-mark]')?.scrollIntoView({ block: 'center' });
	}

	// Copying is the way out of the text (Tobi, 20.10.2026: no download): all of it, also when
	// what is shown stops short.
	async function copy() {
		if (text === null) return;
		let whole = text;
		if (text.length < total) {
			try {
				whole = (await readText(documentId, Infinity)).text;
			} catch (error) {
				toast.error(describeError(error));
				return;
			}
		}
		await copyText(whole);
	}
</script>

<svelte:window onscroll={follow} />

<section
	aria-label={m.view_text()}
	class="flex min-h-[32rem] min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card lg:min-h-0"
>
	<PaneHead {end}>
		<span class="px-1 text-sm text-muted-foreground">
			{#if text !== null}
				{m.text_length({ characters: formatNumber(total) })}
				{#if vision}· {m.vision_read_by()}{/if}
			{/if}
		</span>
		<Button variant="ghost" size="sm" disabled={text === null} onclick={copy}>
			<Copy aria-hidden="true" />
			{m.content_copy()}
		</Button>
	</PaneHead>
	<!-- As set: no wrapping, the card scrolls sideways. -->
	<div bind:this={textBox} class="relative min-h-0 flex-1 overflow-auto" onscroll={follow}>
		{#if problem}
			<p class="p-6 text-destructive" role="alert">{problem}</p>
		{:else if text === null}
			<p class="p-6 text-sm text-muted-foreground">{loading ? m.loading() : m.text_none()}</p>
		{:else}
			{#each pages as page, index (index)}
				<section
					aria-label={m.content_page({ page: index + 1 })}
					data-page={index + 1}
					class="px-7 py-6"
				>
					{#if pages.length > 1}
						<p class="mb-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
							{m.content_page({ page: index + 1 })}
						</p>
					{/if}
					<pre
						class="font-mono text-[13px] leading-relaxed whitespace-pre">{#if marked.length > 0}{#each segmentsOf(text, ranges[index], marked) as segment, at (at)}{#if segment.marked}<mark
										data-mark
										class="rounded-sm bg-primary/20 text-inherit ring-2 ring-primary"
										>{segment.text}</mark
									>{:else}{segment.text}{/if}{/each}{:else}{page}{/if}</pre>
				</section>
				{#if index < pages.length - 1}<hr class="border-muted" />{/if}
			{/each}
		{/if}
	</div>
</section>
