<script lang="ts">
	import { cn, type WithElementRef } from '#lib/utils.ts';
	import type { HTMLAttributes } from 'svelte/elements';

	// A card's title is a heading (`level`, `<h2>` by default) in the size of card titles.
	let {
		ref = $bindable(null),
		class: className,
		level = 2,
		children,
		...restProps
	}: WithElementRef<HTMLAttributes<HTMLHeadingElement>> & { level?: 2 | 3 | 4 } = $props();
</script>

<svelte:element
	this={`h${level}`}
	bind:this={ref}
	data-slot="card-title"
	class={cn('text-md leading-snug font-semibold', className)}
	{...restProps}
>
	{@render children?.()}
</svelte:element>
