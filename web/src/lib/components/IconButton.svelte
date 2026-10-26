<script lang="ts">
	import { mergeProps } from 'bits-ui';
	import type { Snippet } from 'svelte';
	import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
	import { Button, type ButtonVariant } from '#lib/components/ui/button/index.ts';
	import * as Tooltip from '#lib/components/ui/tooltip/index.ts';
	import { cn } from '#lib/utils.ts';

	// A button with an icon only (web/DESIGN.md, "Buttons"): `label` is its name and its tooltip.
	// A rectangle like every button: 40 px (`default`) on pages and in bars, 32 px (`sm`) in rows
	// and cards. On a phone it takes 44 px, a small one by a larger invisible hit area. Spread a
	// trigger's props on it (a menu's "…") to open something; they are merged with the tooltip's.
	let {
		label,
		hint,
		variant = 'ghost',
		size = 'default',
		tooltip = true,
		side = 'top',
		class: className,
		ref = $bindable(null),
		children,
		...rest
	}: HTMLButtonAttributes &
		HTMLAnchorAttributes & {
			label: string;
			/** A shorter tooltip than the name, where the name says more for a screen reader. */
			hint?: string;
			variant?: ButtonVariant;
			size?: 'default' | 'sm';
			/** Off where the label already stands next to it. */
			tooltip?: boolean;
			side?: 'top' | 'bottom' | 'left' | 'right';
			ref?: HTMLElement | null;
			children: Snippet;
		} = $props();

	const look = $derived(
		cn(
			size === 'sm' ? 'relative max-sm:after:absolute max-sm:after:-inset-1.5' : 'max-sm:size-11',
			className
		)
	);
</script>

{#if tooltip}
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}
				<Button
					bind:ref
					{...mergeProps(props, rest)}
					aria-label={label}
					{variant}
					size={size === 'sm' ? 'icon-sm' : 'icon'}
					class={look}
				>
					{@render children()}
				</Button>
			{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Content {side}>{hint ?? label}</Tooltip.Content>
	</Tooltip.Root>
{:else}
	<Button
		bind:ref
		{...rest}
		aria-label={label}
		{variant}
		size={size === 'sm' ? 'icon-sm' : 'icon'}
		class={look}
	>
		{@render children()}
	</Button>
{/if}
