<script lang="ts">
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// Back to the top of a long page where the window scrolls (a phone): it comes once more than
	// a screen lies above and says on which page of the document one stands, `current` of
	// `total` (Tobi, 20.10.2026); with fewer than two pages only the arrow.
	let { current = 0, total = 0 }: { current?: number; total?: number } = $props();

	let scrollY = $state(0);
	let innerHeight = $state(0);
	const far = $derived(innerHeight > 0 && scrollY > innerHeight);
	const counted = $derived(total > 1 && current >= 1);

	function up() {
		const still = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
		window.scrollTo({ top: 0, behavior: still ? 'auto' : 'smooth' });
	}
</script>

<svelte:window bind:scrollY bind:innerHeight />

{#if far}
	<button
		type="button"
		class={cn(
			'fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-30 inline-flex h-11 animate-in items-center gap-1.5 rounded-full border bg-card/90 text-sm font-medium tabular-nums shadow-lg backdrop-blur duration-150 fade-in-0 motion-reduce:animate-none',
			counted ? 'px-4' : 'w-11 justify-center'
		)}
		aria-label={counted ? m.to_top_page({ current, total }) : m.to_top()}
		onclick={up}
	>
		<ArrowUp class="size-4 shrink-0" aria-hidden="true" />
		{#if counted}{m.to_top_count({ current, total })}{/if}
	</button>
{/if}
