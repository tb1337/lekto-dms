<script lang="ts" module>
	import { tv, type VariantProps } from 'tailwind-variants';

	// Every card (web/DESIGN.md, "Cards"): the radius of cards, a hairline border, no shadow; the
	// layout inside is the caller's (`class`). The size sets the padding: `row` for items of a list, `sm` for dense panels, `md` by default,
	// `lg` for the sections of the system page, `flush` for a card whose rows or parts pad
	// themselves.
	export const cardVariants = tv({
		base: 'group/card min-w-0 rounded-2xl border bg-card text-card-foreground',
		variants: {
			size: {
				flush: '',
				row: 'p-4',
				sm: 'p-3.5',
				md: 'p-5',
				lg: 'px-5 py-4 sm:px-6'
			}
		},
		defaultVariants: { size: 'md' }
	});

	export type CardSize = VariantProps<typeof cardVariants>['size'];
</script>

<script lang="ts">
	import { cn, type WithElementRef } from '#lib/utils.ts';
	import type { HTMLAttributes } from 'svelte/elements';

	let {
		ref = $bindable(null),
		class: className,
		children,
		size = 'md',
		as = 'div',
		...restProps
	}: WithElementRef<HTMLAttributes<HTMLElement>> & {
		size?: CardSize;
		as?: 'div' | 'section' | 'article' | 'li' | 'ul' | 'aside' | 'form';
	} = $props();
</script>

<svelte:element
	this={as}
	bind:this={ref}
	data-slot="card"
	data-size={size}
	class={cn(cardVariants({ size }), className)}
	{...restProps}
>
	{@render children?.()}
</svelte:element>
