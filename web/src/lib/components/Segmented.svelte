<script lang="ts" module>
	import type FileIcon from '@lucide/svelte/icons/file';

	export interface Segment {
		value: string;
		label: string;
		icon?: typeof FileIcon;
		/** A longer explanation, shown on hover. */
		hint?: string;
		/** A number after the name (what a tab holds). */
		count?: number | string;
		/** A red dot after the name, read out as this (a problem in there). */
		alert?: string;
	}
</script>

<script lang="ts">
	import { slidingPill } from '#lib/sliding-pill.ts';
	import { cn } from '#lib/utils.ts';

	// One of a few ways to show something (one or two pages, grid or list, a part of a prompt):
	// buttons in a pill, the chosen one on a light pill that moves over (`sliding-pill.ts`), as
	// the tabs of a page do (`TabBar`). `sm` for a toolbar, `md` beside 40 px buttons. Names are
	// `shown`, `wide` (an icon only on a phone), `hidden` (icons only; the name is read out and
	// shown on hover), or shown from a width of the surrounding container on (`@xl`, `@3xl`:
	// in a pane as narrow as it gets). `equal`: every entry as wide as the widest.
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
		names?: 'shown' | 'wide' | 'hidden' | '@xl' | '@3xl';
		equal?: boolean;
		class?: string;
		/** Called with the value the person chose. */
		onchange?: (value: string) => void;
	} = $props();

	// Spelled out, for Tailwind to find them.
	const ROOM = {
		wide: 'sr-only sm:not-sr-only',
		'@xl': 'sr-only @xl:not-sr-only',
		'@3xl': 'sr-only @3xl:not-sr-only'
	} as const;
	const roomy = $derived(names === 'wide' || names === '@xl' || names === '@3xl');

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
			title={option.hint ??
				(names === 'hidden' || names.startsWith('@') ? option.label : undefined)}
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
				<span class={cn(roomy && option.icon && ROOM[names as keyof typeof ROOM])}>
					{option.label}
				</span>
			{/if}
			{#if option.count !== undefined}
				<span class="text-xs font-normal text-muted-foreground tabular-nums">{option.count}</span>
			{/if}
			{#if option.alert}
				<span class="size-[7px] rounded-full bg-destructive" aria-hidden="true"></span>
				<span class="sr-only">{option.alert}</span>
			{/if}
		</button>
	{/each}
</div>
