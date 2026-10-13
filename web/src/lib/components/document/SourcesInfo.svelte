<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import type { Candidate } from '#lib/candidates.ts';
	import CandidateSources from '#lib/components/document/CandidateSources.svelte';
	import { m } from '#lib/paraglide/messages.js';

	// Where a checked value comes from, behind an info icon: on hover, on focus, on a tap. It
	// stays open while the pointer or the focus is in it, so its links can be followed, and
	// closes with Escape.
	let { candidates, id }: { candidates: readonly Candidate[]; id: string } = $props();

	let open = $state(false);

	function left(event: FocusEvent & { currentTarget: HTMLElement }) {
		if (!event.currentTarget.contains(event.relatedTarget as Node | null)) open = false;
	}
</script>

<span
	role="presentation"
	class="relative inline-flex"
	onmouseenter={() => (open = true)}
	onmouseleave={() => (open = false)}
	onfocusin={() => (open = true)}
	onfocusout={left}
	onkeydown={(event) => event.key === 'Escape' && (open = false)}
>
	<button
		type="button"
		aria-label={m.sources_details()}
		aria-controls={id}
		aria-expanded={open}
		onclick={() => (open = true)}
		class="grid size-6 place-items-center rounded-full text-muted-foreground hover:text-foreground"
	>
		<Info class="size-3.5" aria-hidden="true" />
	</button>
	{#if open}
		<div
			{id}
			class="absolute top-full right-0 z-20 flex w-72 flex-col gap-2 rounded-xl bg-foreground px-3.5 py-3 text-[12.5px] leading-normal text-background shadow-lg"
		>
			<p class="font-semibold">{m.sources_details()}</p>
			{#each candidates as candidate, index (index)}
				<div class="flex flex-col gap-1">
					{#if candidates.length > 1}<span>{candidate.label}</span>{/if}
					<CandidateSources {candidate} inverted />
				</div>
			{/each}
		</div>
	{/if}
</span>
