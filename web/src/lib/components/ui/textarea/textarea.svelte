<script lang="ts">
	import { cn, type WithElementRef, type WithoutChildren } from '#lib/utils.ts';
	import type { HTMLTextareaAttributes } from 'svelte/elements';
	import { FIELD } from '../field-look.ts';

	let {
		ref = $bindable(null),
		value = $bindable(),
		class: className,
		'data-slot': dataSlot = 'textarea',
		...restProps
	}: WithoutChildren<WithElementRef<HTMLTextareaAttributes>> = $props();
</script>

<textarea
	bind:this={ref}
	data-slot={dataSlot}
	class={cn(FIELD, 'flex field-sizing-content min-h-16 py-2.5', className)}
	bind:value
	{...restProps}></textarea>
