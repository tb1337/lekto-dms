<script lang="ts">
	import { Tooltip as TooltipPrimitive } from 'bits-ui';
	import { cn } from '#lib/utils.ts';

	// The dark box of a tooltip, as the info tips have it (web/DESIGN.md, "Help and tooltips"). It
	// fades in after its delay but goes at once, so that it never stands beside the next one:
	// hidden the moment it closes, before bits-ui takes it out a frame later.
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
			'z-[70] max-w-72 rounded-lg bg-foreground px-2.5 py-1.5 text-xs text-background shadow-md data-[state=closed]:hidden data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0',
			className
		)}
		{...restProps}
	/>
</TooltipPrimitive.Portal>
