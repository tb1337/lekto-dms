<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.ts';

	// A list with nothing in it: a dashed box with the words for it, as every page shows it, and
	// where there is one the way to what would fill it (`action`; web/DESIGN.md, "States").
	let {
		compact = false,
		class: className,
		action,
		children
	}: { compact?: boolean; class?: string; action?: Snippet; children: Snippet } = $props();
</script>

<div
	class={cn(
		'flex flex-col items-center gap-4 rounded-2xl border border-dashed bg-card px-6 text-center text-muted-foreground',
		compact ? 'py-10' : 'py-16',
		className
	)}
>
	<p>{@render children()}</p>
	{@render action?.()}
</div>
