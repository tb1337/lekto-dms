<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn } from '#lib/utils.ts';

	// The title of a section of a page (`section`, `text-lg`) or of a card or pane (`card`,
	// `text-md`), web/DESIGN.md, "Typography". The level follows the outline of the page, not the
	// look: a card's title on a page is an `<h2>`, inside a section an `<h3>`.
	let {
		level = 2,
		size = 'section',
		class: className,
		children,
		...rest
	}: HTMLAttributes<HTMLHeadingElement> & {
		level?: 2 | 3 | 4;
		size?: 'section' | 'card';
		children: Snippet;
	} = $props();
</script>

<svelte:element
	this={`h${level}`}
	class={cn('font-semibold', size === 'section' ? 'text-lg' : 'text-md leading-tight', className)}
	{...rest}
>
	{@render children()}
</svelte:element>
