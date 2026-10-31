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
		/** Not to be chosen now; the text near the bar says why. */
		disabled?: boolean;
	}
</script>

<script lang="ts">
	import SteadyText from '#lib/components/SteadyText.svelte';
	import { slidingPill } from '#lib/sliding-pill.ts';
	import { cn } from '#lib/utils.ts';
	import * as Tooltip from '#lib/components/ui/tooltip/index.ts';
	import { mergeProps } from 'bits-ui';

	// One of a few ways to show something (one or two pages, grid or list, a part of a prompt):
	// buttons in a pill, the chosen one on a light pill that moves over (`sliding-pill.ts`), as
	// the tabs of a page do (`TabBar`). `sm` for a toolbar, `md` beside 40 px buttons. Names are
	// `shown`, `wide` (an icon only on a phone), `hidden` (icons only; the name is read out and
	// shown on hover), or shown from a width of the surrounding container on (`@xl`, `@3xl`:
	// in a pane as narrow as it gets). `equal`: every entry as wide as the widest. Where the bar
	// is wider than the room (a phone), it scrolls sideways, the chosen one in view, and the cut
	// edge fades, as the tabs of a page do.
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

	let room = $state<HTMLElement | null>(null);
	/** Which edges have more behind them. */
	let more = $state<{ start: boolean; end: boolean }>({ start: false, end: false });

	function measure() {
		if (!room) return;
		const end = room.scrollWidth - room.clientWidth - room.scrollLeft;
		more = { start: room.scrollLeft > 1, end: end > 1 };
	}

	$effect(() => {
		void value;
		void options;
		const chosen = room?.querySelector<HTMLElement>('[aria-pressed="true"]');
		if (!room || !chosen) return;
		const left = chosen.offsetLeft - (room.clientWidth - chosen.offsetWidth) / 2;
		room.scrollLeft = Math.max(0, left);
		measure();
	});

	$effect(() => {
		if (!room) return;
		const sizes = new ResizeObserver(measure);
		sizes.observe(room);
		for (const child of room.children) sizes.observe(child);
		return () => sizes.disconnect();
	});

	function choose(next: string) {
		if (next === value) return;
		value = next;
		onchange?.(next);
	}
</script>

{#snippet entry(option: Segment, props: Record<string, unknown>)}
	{@const chosen = option.value === value}
	<button
		{...mergeProps(props, { onclick: () => choose(option.value) })}
		type="button"
		aria-pressed={chosen}
		aria-label={names === 'hidden' ? option.label : undefined}
		disabled={option.disabled}
		class={cn(
			'relative inline-flex items-center justify-center rounded-full whitespace-nowrap transition-colors disabled:opacity-50',
			size === 'sm' ? 'h-7 gap-1.5 px-2.5 text-xs' : 'h-8 gap-2 px-3 text-sm',
			names === 'hidden' && (size === 'sm' ? 'w-7 px-0 max-sm:w-10' : 'w-8 px-0 max-sm:w-11'),
			// A finger's tap on a phone: 44 pixels high, the bar keeps its look.
			size === 'sm'
				? 'max-sm:after:absolute max-sm:after:inset-x-0 max-sm:after:-inset-y-2'
				: 'max-sm:after:absolute max-sm:after:inset-x-0 max-sm:after:-inset-y-1.5',
			chosen ? 'font-medium text-foreground' : 'text-muted-foreground enabled:hover:text-foreground'
		)}
	>
		{#if option.icon}
			<option.icon class={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden="true" />
		{/if}
		{#if names !== 'hidden'}
			<SteadyText
				text={option.label}
				class={cn(roomy && option.icon && ROOM[names as keyof typeof ROOM])}
			/>
		{/if}
		{#if option.count !== undefined}
			<span class="text-xs font-normal text-muted-foreground tabular-nums">{option.count}</span>
		{/if}
		{#if option.alert}
			<span class="size-[7px] rounded-full bg-destructive" aria-hidden="true"></span>
			<span class="sr-only">{option.alert}</span>
		{/if}
	</button>
{/snippet}

<!-- The room the bar scrolls in; on a phone as much taller as the hit areas reach beyond the
     bar, so that it does not cut them. -->
<div
	bind:this={room}
	onscroll={measure}
	data-more-start={more.start || undefined}
	data-more-end={more.end || undefined}
	class={cn(
		'w-fit max-w-full [scrollbar-width:none] overflow-x-auto',
		size === 'sm' ? 'max-sm:-my-1.5 max-sm:py-1.5' : 'max-sm:-my-0.5 max-sm:py-0.5',
		'data-more-end:[mask-image:linear-gradient(to_right,black_85%,transparent)]',
		'data-more-start:[mask-image:linear-gradient(to_left,black_85%,transparent)]',
		'data-more-start:data-more-end:[mask-image:linear-gradient(to_right,transparent,black_15%,black_85%,transparent)]',
		className
	)}
>
	<div
		role="group"
		aria-label={labelledby ? undefined : label}
		aria-labelledby={labelledby}
		{@attach slidingPill}
		class={cn(
			'relative flex w-max min-w-full items-center rounded-full bg-secondary',
			size === 'sm' ? 'gap-0.5 p-[3px]' : 'h-10 gap-0.5 p-1',
			equal && 'grid auto-cols-fr grid-flow-col'
		)}
	>
		<span
			data-pill
			hidden
			aria-hidden="true"
			class="pointer-events-none absolute top-0 left-0 rounded-full bg-card shadow-sm data-moving:motion-safe:transition-[transform,width,height] data-moving:motion-safe:duration-300 data-moving:motion-safe:ease-out"
		></span>
		{#each options as option (option.value)}
			{@const tip =
				option.hint ?? (names === 'hidden' || names.startsWith('@') ? option.label : undefined)}
			{#if tip}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}{@render entry(option, props)}{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>{tip}</Tooltip.Content>
				</Tooltip.Root>
			{:else}
				{@render entry(option, {})}
			{/if}
		{/each}
	</div>
</div>
