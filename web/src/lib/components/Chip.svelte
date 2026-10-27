<script lang="ts" module>
	/** The ✕ of a removable chip: round inside the pill, its tap reaching beyond its edges on the
	 * right and above and below (never over the name), so that a finger hits it on a phone. */
	export const CHIP_REMOVE =
		'relative grid size-6 shrink-0 place-items-center rounded-full opacity-70 hover:bg-background hover:opacity-100 after:absolute after:-inset-y-2.5 after:-right-2.5 after:left-0';
</script>

<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.ts';

	// The one chip (web/DESIGN.md, "Chips"): a pill with an optional icon and a name. `neutral`
	// for free values and search words, `outline` for a group or a quiet value, `selected` for
	// what is chosen (an active filter), `add` the dashed "+ …" that opens a picker. With
	// `pressed` it is a toggle (`aria-pressed`, a check when on); with `onremove` it has a ✕.
	// Tags and topics in their colours are `TagChip`, drawn in the same shape.
	let {
		variant = 'neutral',
		size = 'md',
		pressed,
		onclick,
		onremove,
		removeLabel = '',
		icon,
		class: className,
		children,
		...rest
	}: {
		variant?: 'neutral' | 'outline' | 'selected' | 'add';
		size?: 'sm' | 'md';
		/** A toggle: on or off. */
		pressed?: boolean;
		onclick?: (event: MouseEvent) => void;
		onremove?: () => void;
		removeLabel?: string;
		icon?: Snippet;
		class?: string;
		children: Snippet;
		[key: string]: unknown;
	} = $props();

	const toggle = $derived(pressed !== undefined);
	const look = $derived(
		cn(
			'inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full whitespace-nowrap transition-colors',
			size === 'sm' ? 'h-6 px-2 text-xs' : 'h-8 px-3 text-sm',
			onremove && (size === 'sm' ? 'pr-0.5' : 'pr-1'),
			toggle
				? pressed
					? 'bg-panel font-medium text-brand ring-1 ring-primary/30 ring-inset'
					: 'border bg-card hover:bg-secondary'
				: {
						neutral: 'bg-secondary text-foreground',
						outline: 'border bg-card',
						selected: 'bg-panel text-brand ring-1 ring-primary/30 ring-inset',
						add: 'border border-dashed border-muted-foreground/50 text-brand hover:bg-secondary'
					}[variant],
			// A finger's tap on a phone: 44 pixels high around the pill.
			(toggle || variant === 'add' || onclick) &&
				'relative max-sm:after:absolute max-sm:after:inset-x-0 max-sm:after:-inset-y-1.5',
			className
		)
	);
</script>

{#if toggle || variant === 'add' || onclick}
	<button type="button" aria-pressed={pressed} {onclick} class={look} {...rest}>
		{#if pressed}<Check class="size-3.5 shrink-0" aria-hidden="true" />{/if}
		{@render icon?.()}
		<span class="min-w-0 truncate">{@render children()}</span>
	</button>
{:else}
	<span class={look} {...rest}>
		{@render icon?.()}
		<span class="min-w-0 truncate">{@render children()}</span>
		{#if onremove}
			<button type="button" class={CHIP_REMOVE} aria-label={removeLabel} onclick={onremove}>
				<X class="size-3.5" aria-hidden="true" />
			</button>
		{/if}
	</span>
{/if}
