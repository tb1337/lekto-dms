<script lang="ts">
	import type { Candidate } from '#lib/candidates.ts';
	import CandidateSources from '#lib/components/document/CandidateSources.svelte';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import { m } from '#lib/paraglide/messages.js';

	// Where a checked value comes from, behind an info icon (`InfoTip`: it stays open while the
	// mouse is in it, so its links can be followed).
	let { candidates, id }: { candidates: readonly Candidate[]; id: string } = $props();

	// The language model's value is a match of names, no probability: said once below.
	const matched = $derived(
		candidates.some((candidate) =>
			candidate.sources.some((source) => source.signal === 'signal_llm' && source.score != null)
		)
	);
</script>

<InfoTip label={m.sources_details()} {id} size="sm" class="flex w-72 flex-col gap-2">
	<p class="font-semibold">{m.sources_details()}</p>
	{#each candidates as candidate, index (index)}
		<div class="flex flex-col gap-1">
			{#if candidates.length > 1}<span>{candidate.label}</span>{/if}
			<CandidateSources {candidate} inverted />
		</div>
	{/each}
	{#if matched}<p class="text-background/70">{m.candidate_llm_note()}</p>{/if}
</InfoTip>
