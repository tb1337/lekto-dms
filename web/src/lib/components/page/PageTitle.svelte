<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn } from '#lib/utils.ts';

	// The title of a page, its one `<h1>` (web/DESIGN.md, "Page frame"). Long German words break
	// with hyphens instead of being cut; a word that cannot (a file name) breaks anywhere rather
	// than widening the page.
	let {
		class: className,
		children,
		...rest
	}: HTMLAttributes<HTMLHeadingElement> & { children: Snippet } = $props();
</script>

<h1 class={cn('text-title wrap-anywhere hyphens-auto', className)} {...rest}>
	{@render children()}
</h1>
