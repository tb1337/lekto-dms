<script lang="ts" module>
	import type FileIcon from '@lucide/svelte/icons/file';

	export interface Segment {
		value: string;
		label: string;
		icon?: typeof FileIcon;
		/** A longer explanation, shown on hover. */
		hint?: string;
	}
</script>

<script lang="ts">
	import { slidingPill } from '#lib/sliding-pill.ts';
	import { cn } from '#lib/utils.ts';

	// One of a few ways to show something (one or two pages, grid or list, a part of a prompt):
	// buttons in a pill, the chosen one on a light pill that moves over (`sliding-pill.ts`), as
	// the tabs of a page do (`TabBar`). `sm` for a toolbar, `md` beside 40 px buttons. Names are
	// `shown`, `wide` (an icon only on a phone) or `hidden` (icons only; the name is read out and
	// shown on hover). `equal`: every entry as wide as the widest.
	let {
		value = $bindable(''),
		options,
		label,
		labelledby,
		size = 'md',
		names = 'shown',
		equal = false,
		class: className = '',
		onchange
	}: {
		value?: string;
		options: readonly Segment[];
		/** Names the group, unless `labelledby` does. */
		label?: string;
		labelledby?: string;
		size?: 'sm' | 'md';
		names?: 'shown' | 'wide' | 'hidden';
		equal?: boolean;
		class?: string;
		/** Called with the value the person chose. */
		onchange?: (value: string) => void;
	} = $props();

	function choose(next: string) {
		if (next === value) return;
		value = next;
		onchange?.(next);
	}
</script>

<div
	role="group"
	aria-label={labelledby ? undefined : label}
	aria-labelledby={labelledby}
	{@attach slidingPill}
	class={cn(
		'relative flex w-fit max-w-full items-center rounded-full bg-secondary',
		size === 'sm' ? 'gap-0.5 p-[3px]' : 'h-10 gap-0.5 p-1',
		equal && 'grid auto-cols-fr grid-flow-col',
		className
	)}
>
	<span
		data-pill
		hidden
		aria-hidden="true"
		class="pointer-events-none absolute top-0 left-0 rounded-full bg-card shadow-sm data-moving:motion-safe:transition-[transform,width,height] data-moving:motion-safe:duration-300 data-moving:motion-safe:ease-out"
	></span>
	{#each options as option (option.value)}
		{@const chosen = option.value === value}
		<button
			type="button"
			aria-pressed={chosen}
			aria-label={names === 'hidden' ? option.label : undefined}
			title={option.hint ?? (names === 'hidden' ? option.label : undefined)}
			onclick={() => choose(option.value)}
			class={cn(
				'relative inline-flex items-center justify-center rounded-full whitespace-nowrap transition-colors',
				size === 'sm' ? 'h-7 gap-1.5 px-2.5 text-xs' : 'h-8 gap-2 px-3 text-sm',
				names === 'hidden' && (size === 'sm' ? 'w-7 px-0' : 'w-8 px-0'),
				chosen ? 'font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'
			)}
		>
			{#if option.icon}
				<option.icon class={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden="true" />
			{/if}
			{#if names !== 'hidden'}
				<span class={cn(names === 'wide' && option.icon && 'sr-only sm:not-sr-only')}>
					{option.label}
				</span>
			{/if}
		</button>
	{/each}
</div>
