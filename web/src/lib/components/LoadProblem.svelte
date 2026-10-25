<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A page or panel could not load: what went wrong, and a way to try again. `children` are
	// further actions beside the retry button.
	let {
		problem,
		onretry,
		buttonClass,
		children
	}: { problem: string; onretry?: () => void; buttonClass?: string; children?: Snippet } = $props();
</script>

<div class="flex flex-col items-start gap-3" role="alert">
	<p class="text-destructive">{problem}</p>
	{#if onretry || children}
		<div class="flex flex-wrap gap-2">
			{#if onretry}
				<Button variant="outline" class={buttonClass} onclick={onretry}>{m.retry()}</Button>
			{/if}
			{@render children?.()}
		</div>
	{/if}
</div>
