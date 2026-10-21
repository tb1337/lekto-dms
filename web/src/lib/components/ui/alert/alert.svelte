<script lang="ts" module>
	import { type VariantProps, tv } from 'tailwind-variants';

	export const alertVariants = tv({
		base: "grid gap-0.5 rounded-lg border px-2.5 py-2 text-left text-sm has-data-[slot=alert-action]:relative has-data-[slot=alert-action]:pr-18 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-2 *:[svg]:row-span-2 *:[svg]:translate-y-0.5 *:[svg]:text-current *:[svg:not([class*='size-'])]:size-4 group/alert relative w-full",
		variants: {
			variant: {
				default: 'bg-card text-card-foreground',
				destructive:
					'text-destructive bg-card *:data-[slot=alert-description]:text-destructive/90 *:[svg]:text-current',
				// Admonitions, as GitHub and Docusaurus name them, each with its icon. A tip is blue,
				// not green: green is the lane of what is done (Tobi, 21.10.2026).
				note: 'border-note-foreground/25 bg-note text-note-foreground *:data-[slot=alert-description]:text-note-foreground',
				tip: 'border-note-foreground/25 bg-note text-note-foreground *:data-[slot=alert-description]:text-note-foreground',
				warning:
					'border-lane-yellow-foreground/25 bg-lane-yellow text-lane-yellow-foreground *:data-[slot=alert-description]:text-lane-yellow-foreground',
				caution:
					'border-lane-red-foreground/25 bg-lane-red text-lane-red-foreground *:data-[slot=alert-description]:text-lane-red-foreground'
			}
		},
		defaultVariants: {
			variant: 'default'
		}
	});

	export type AlertVariant = VariantProps<typeof alertVariants>['variant'];
</script>

<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import Lightbulb from '@lucide/svelte/icons/lightbulb';
	import OctagonAlert from '@lucide/svelte/icons/octagon-alert';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { cn, type WithElementRef } from '#lib/utils.ts';
	import type { HTMLAttributes } from 'svelte/elements';

	// The admonitions bring their icon.
	const ICONS = { note: Info, tip: Lightbulb, warning: TriangleAlert, caution: OctagonAlert };

	let {
		ref = $bindable(null),
		class: className,
		variant = 'default',
		children,
		...restProps
	}: WithElementRef<HTMLAttributes<HTMLDivElement>> & {
		variant?: AlertVariant;
	} = $props();
</script>

<div
	bind:this={ref}
	data-slot="alert"
	role="alert"
	class={cn(alertVariants({ variant }), className)}
	{...restProps}
>
	{#if variant && variant in ICONS}
		{@const Icon = ICONS[variant as keyof typeof ICONS]}
		<Icon aria-hidden="true" />
	{/if}
	{@render children?.()}
</div>
