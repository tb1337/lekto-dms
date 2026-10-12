<script lang="ts">
	import { untrack } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The recognised text of a document, as soon as the parse node is done; more on request.
	let { documentId }: { documentId: string } = $props();

	const PIECE = 20_000;
	let text = $state<string | null>(null);
	let total = $state(0);
	let next = $state<number | null>(null);
	let problem = $state<string | null>(null);
	let busy = $state(false);

	// An answer overtaken by a later request (several events at once) must not replace the
	// current text.
	let latest = 0;
	async function load(offset = 0) {
		const wanted = documentId;
		const request = ++latest;
		busy = true;
		try {
			const piece = await unwrap(
				api.GET('/api/v1/documents/{id}/text', {
					params: { path: { id: wanted }, query: { offset, limit: PIECE } }
				})
			);
			if (wanted !== documentId || request !== latest) return;
			text = offset === 0 ? piece.text : (text ?? '') + piece.text;
			total = piece.total_length;
			next = piece.next_offset;
			problem = null;
		} catch (error) {
			if (wanted !== documentId || request !== latest) return;
			// 409: not parsed yet; the next event brings the text.
			if (error instanceof ApiError && error.status === 409) {
				text = null;
				problem = null;
			} else problem = describeError(error);
		} finally {
			if (request === latest) busy = false;
		}
	}

	$effect(() => {
		void documentId;
		untrack(() => {
			text = null;
			next = null;
			problem = null;
		});
		void events.generation;
		void load();
		return events.subscribe((event) => {
			if (event.document_id === documentId && event.type === 'document.node_completed') void load();
		});
	});
</script>

{#if problem}
	<p class="text-destructive" role="alert">{problem}</p>
{:else if text === null}
	<p class="text-sm text-muted-foreground">{m.text_none()}</p>
{:else}
	<p class="text-xs text-muted-foreground">
		{m.text_length({ characters: formatNumber(total) })}
	</p>
	<pre
		class="max-h-96 overflow-auto rounded-xl border bg-card p-4 text-sm whitespace-pre-wrap">{text}</pre>
	{#if next !== null}
		<Button variant="outline" disabled={busy} onclick={() => load(next ?? 0)}>
			{m.text_more()}
		</Button>
	{/if}
{/if}
