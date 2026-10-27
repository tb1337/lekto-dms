<script lang="ts">
	import { Separator as SeparatorPrimitive } from 'bits-ui';
	import { cn } from '#lib/utils.ts';

	let {
		ref = $bindable(null),
		class: className,
		'data-slot': dataSlot = 'separator',
		orientation = 'horizontal',
		...restProps
	}: SeparatorPrimitive.RootProps = $props();
</script>

<SeparatorPrimitive.Root
	bind:ref
	data-slot={dataSlot}
	{orientation}
	class={cn(
		// Plain classes by orientation, not `data-[orientation=…]:` ones: those would beat a
		// caller's `self-center` or `h-5`, and a short vertical line would hang from the top.
		'shrink-0 bg-border',
		orientation === 'vertical' ? 'w-px self-stretch' : 'h-px w-full',
		className
	)}
	{...restProps}
/>
