<script lang="ts">
	import { Tooltip as TooltipPrimitive } from 'bits-ui';
	import { cn } from '#lib/utils.ts';

	// The dark box of a tooltip, as the info tips have it (web/DESIGN.md, "Help and tooltips").
	let {
		ref = $bindable(null),
		class: className,
		sideOffset = 6,
		...restProps
	}: TooltipPrimitive.ContentProps = $props();
</script>

<TooltipPrimitive.Portal>
	<TooltipPrimitive.Content
		bind:ref
		data-slot="tooltip-content"
		{sideOffset}
		collisionPadding={8}
		class={cn(
			'z-50 max-w-72 rounded-lg bg-foreground px-2.5 py-1.5 text-xs text-background shadow-md data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0',
			className
		)}
		{...restProps}
	/>
</TooltipPrimitive.Portal>
