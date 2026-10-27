<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn } from '#lib/utils.ts';

	// The small label in capitals above a group ("Lenses", "Zeitraum", a phase of a run), the one
	// look for it (web/DESIGN.md, "Typography"). `as` keeps the outline right: a heading where it
	// heads a group, a `p` or `span` where it only labels.
	let {
		as = 'p',
		class: className,
		children,
		...rest
	}: HTMLAttributes<HTMLElement> & {
		as?: 'p' | 'span' | 'h2' | 'h3' | 'h4' | 'div';
		children: Snippet;
	} = $props();
</script>

<svelte:element
	this={as}
	class={cn('text-xs font-medium tracking-wide text-muted-foreground uppercase', className)}
	{...rest}
>
	{@render children()}
</svelte:element>
