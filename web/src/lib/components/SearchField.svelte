<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import { cn } from '#lib/utils.ts';

	// A search field as the pickers have it: a magnifier, then the input, named and prompted by
	// `label`, in a frame the caller shapes (`class`: height, corners, ground, border, focus).
	let {
		value = $bindable(''),
		label,
		size = 'md',
		class: className,
		ref = $bindable(null)
	}: {
		value?: string;
		label: string;
		/** The magnifier: `sm` in a low field. */
		size?: 'sm' | 'md';
		class?: string;
		/** The input, for the focus. */
		ref?: HTMLInputElement | null;
	} = $props();
</script>

<label class={cn('flex items-center gap-2 text-muted-foreground', className)}>
	<SearchIcon class={cn('shrink-0', size === 'sm' ? 'size-3.5' : 'size-4')} aria-hidden="true" />
	<input
		bind:this={ref}
		bind:value
		type="search"
		aria-label={label}
		placeholder={label}
		class="h-full min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm"
	/>
</label>
