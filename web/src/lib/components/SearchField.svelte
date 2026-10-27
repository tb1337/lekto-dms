<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import { FIELD_FRAME } from '#lib/components/ui/field-look.ts';
	import { cn } from '#lib/utils.ts';

	// Every search field (web/DESIGN.md, "Fields"): a magnifier, then the input, in the frame of
	// the fields. `md` stands in pages, pickers and dialogs, `sm` in dense panels (a filter group).
	// `class` sets the width; `label` names the input and prompts it unless `placeholder` says more.
	let {
		value = $bindable(''),
		label,
		placeholder,
		size = 'md',
		class: className,
		ref = $bindable(null),
		onkeydown
	}: {
		value?: string;
		label: string;
		placeholder?: string;
		size?: 'sm' | 'md';
		class?: string;
		/** The input, for the focus. */
		ref?: HTMLInputElement | null;
		onkeydown?: (event: KeyboardEvent) => void;
	} = $props();
</script>

<label
	class={cn(FIELD_FRAME, size === 'sm' ? 'h-8 gap-1.5 px-2.5' : 'h-11 px-3.5 sm:h-10', className)}
>
	<SearchIcon class={cn('shrink-0', size === 'sm' ? 'size-3.5' : 'size-4')} aria-hidden="true" />
	<input
		bind:this={ref}
		bind:value
		type="search"
		aria-label={label}
		placeholder={placeholder ?? label}
		{onkeydown}
		class="h-full min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm"
	/>
</label>
