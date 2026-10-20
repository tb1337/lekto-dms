<script lang="ts">
	import type { Snippet } from 'svelte';
	import FactsPanel from '#lib/components/document/FactsPanel.svelte';
	import PaneHead from '#lib/components/document/PaneHead.svelte';
	import {
		factCounts,
		factsSummary,
		type CodeFacts,
		type CodePlace,
		type Facts,
		type Span
	} from '#lib/facts.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The facts of the document as a pane of the document tab: what it shows of its contact
	// and its codes, counted in the head, on the inner surface below.
	let {
		facts = null,
		documentId,
		lookup = null,
		topicId = null,
		admin = false,
		onmark,
		onshowcode,
		onchanged,
		end
	}: {
		facts?: Facts | null;
		documentId: string;
		lookup?: Lookup | null;
		/** The document's topic: identifiers attached point to it by default. */
		topicId?: string | null;
		/** Admins attach identifiers to contacts. */
		admin?: boolean;
		onmark: (spans: Span[], reveal: boolean) => void;
		onshowcode: (code: CodeFacts, place: CodePlace) => void;
		/** After an identifier was attached: the facts are read again. */
		onchanged: () => void;
		/** At the end of the head: the pane's switch. */
		end?: Snippet;
	} = $props();
</script>

<aside
	aria-label={m.facts_title()}
	class="flex min-h-[32rem] min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card lg:min-h-0"
>
	<PaneHead {end}>
		{#if facts}
			<span class="px-1 text-sm text-muted-foreground">{factsSummary(factCounts(facts))}</span>
		{/if}
	</PaneHead>
	<div class="relative min-h-0 flex-1 overflow-y-auto bg-surface p-3.5">
		{#if facts}
			<FactsPanel
				{facts}
				{documentId}
				{lookup}
				{topicId}
				{admin}
				{onmark}
				{onshowcode}
				{onchanged}
			/>
		{:else}
			<p class="p-2 text-sm text-muted-foreground">{m.facts_pending()}</p>
		{/if}
	</div>
</aside>
