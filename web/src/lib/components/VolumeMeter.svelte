<script lang="ts">
	import { cn } from '#lib/utils.ts';

	// How loud something is, as three short bars rising like a signal (Tobi, 27.10.2026: how
	// often a webhook event comes for one document). Only beside a text that says it in words;
	// the bars themselves are not read out.
	let { level, class: className }: { level: 1 | 2 | 3; class?: string } = $props();
</script>

<span class={cn('inline-flex items-end gap-0.5', className)} aria-hidden="true" data-level={level}>
	{#each [1, 2, 3] as bar (bar)}
		<span
			class={cn(
				'w-1 rounded-full',
				bar === 1 ? 'h-1.5' : bar === 2 ? 'h-2.5' : 'h-3.5',
				bar <= level ? 'bg-muted-foreground' : 'bg-border'
			)}
		></span>
	{/each}
</span>
