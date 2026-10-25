<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.ts';

	// A list with nothing in it: a dashed box with the words for it, as every page shows it.
	let {
		compact = false,
		class: className,
		children
	}: { compact?: boolean; class?: string; children: Snippet } = $props();
</script>

<p
	class={cn(
		'rounded-2xl border border-dashed bg-card px-6 text-center text-muted-foreground',
		compact ? 'py-10' : 'py-16',
		className
	)}
>
	{@render children()}
</p>
