<script lang="ts">
	import { documentHref, sourceChips, type Candidate } from '#lib/candidates.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// What each signal said about a value: a chip per signal, solid where it counts for the
	// judge, dashed where the signal was not sure enough; the similar documents open on a click.
	let { candidate, inverted = false }: { candidate: Candidate; inverted?: boolean } = $props();

	const chips = $derived(candidate.sources.flatMap(sourceChips));
</script>

<span class="flex flex-wrap items-center gap-1">
	{#each chips as chip, index (index)}
		<span
			title={[chip.note, chip.quote && `„${chip.quote}“`].filter(Boolean).join(' ') || undefined}
			class={cn(
				'inline-flex items-center gap-1 rounded-full px-2 text-micro leading-5 whitespace-nowrap',
				chip.strong
					? inverted
						? 'bg-background/15'
						: 'bg-panel'
					: 'border border-dashed border-current/40 opacity-80'
			)}
		>
			{chip.text}
			{#if chip.quote}<span class="sr-only">: „{chip.quote}“</span>{/if}
			{#if chip.note}<span class="sr-only">({chip.note})</span>{/if}
			{#if !chip.strong}<span class="sr-only">({m.candidate_weak()})</span>{/if}
			{#each chip.documents as id, number (id)}
				<a
					href={documentHref(id)}
					aria-label={m.candidate_document({ number: number + 1 })}
					class={cn('font-mono hover:underline', inverted ? 'underline' : 'text-brand')}
				>
					{number + 1}
				</a>
			{/each}
		</span>
	{/each}
</span>
