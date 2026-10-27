<script lang="ts">
	import { cn, type WithElementRef } from '#lib/utils.ts';
	import type { HTMLInputAttributes, HTMLInputTypeAttribute } from 'svelte/elements';
	import { FIELD, FIELD_HEIGHT } from '../field-look.ts';

	type InputType = Exclude<HTMLInputTypeAttribute, 'file'>;

	type Props = WithElementRef<
		Omit<HTMLInputAttributes, 'type'> &
			({ type: 'file'; files?: FileList } | { type?: InputType; files?: undefined })
	>;

	let {
		ref = $bindable(null),
		value = $bindable(),
		type,
		files = $bindable(),
		class: className,
		'data-slot': dataSlot = 'input',
		...restProps
	}: Props = $props();
</script>

{#if type === 'file'}
	<input
		bind:this={ref}
		data-slot={dataSlot}
		class={cn(
			FIELD,
			FIELD_HEIGHT,
			'py-1 file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground',
			className
		)}
		type="file"
		bind:files
		bind:value
		{...restProps}
	/>
{:else}
	<input
		bind:this={ref}
		data-slot={dataSlot}
		class={cn(
			FIELD,
			FIELD_HEIGHT,
			'py-1 file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground',
			className
		)}
		{type}
		bind:value
		{...restProps}
	/>
{/if}
