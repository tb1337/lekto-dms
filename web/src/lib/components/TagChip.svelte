<script lang="ts" module>
	import { chipStyle, isHex } from '#lib/colors.ts';
	import { cn } from '#lib/utils.ts';

	/** The colours of a chip, a pill like every chip (web/DESIGN.md, "Chips"): filled for a tag,
	 * filled with an edge for a topic, outlined for a group; in `color` where it has one
	 * (`chipStyle` sets the variables). An own colour may be close to the card (white in light,
	 * black in dark): with `ring`, a faint ring keeps a tag's shape. */
	export function chipLook(
		kind: 'tag' | 'topic' | 'group',
		color: string | null | undefined,
		ring = true
	): string {
		const coloured = chipStyle(color) !== null;
		return cn(
			'inline-flex max-w-full min-w-0 items-center gap-1',
			'rounded-full',
			kind === 'topic' && 'border',
			!coloured &&
				(kind === 'topic'
					? 'border-primary/25 bg-primary/10'
					: kind === 'group'
						? 'border bg-background'
						: 'bg-secondary'),
			coloured &&
				(kind === 'group'
					? 'border border-(--chip-fg)/45 bg-background text-(--chip-fg)'
					: cn(
							'bg-(--chip-bg) font-medium text-(--chip-fg)',
							kind === 'topic' && 'border-(--chip-fg)/25'
						)),
			isHex(color) && 'chip-own',
			isHex(color) && kind === 'tag' && ring && 'ring-1 ring-(--chip-fg)/15 ring-inset'
		);
	}
</script>

<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import LucideIcon from '#lib/components/LucideIcon.svelte';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import type { Tag } from '#lib/masterdata.svelte.ts';
	import { pathLabel } from '#lib/tags.ts';
	import { CHIP_REMOVE } from '#lib/components/Chip.svelte';

	// A tag as a chip: its icon and own name in its colour, the path as tooltip and, where
	// `interactive`, on a tap (a phone has no hover); a group outlined, a topic with an edge;
	// `onremove` adds a button that removes it. On a phone both take a finger's tap
	// beyond their edges (44 pixels high; the button also to its right, never over the name).
	// `onImage`: on a document's image (a card), as glass with an edge (`.mark-glass`).
	let {
		tag,
		group = false,
		topic = false,
		interactive = false,
		size = 'md',
		onImage = false,
		onremove,
		removeLabel = ''
	}: {
		tag: Pick<Tag, 'id' | 'name' | 'path'> & Partial<Pick<Tag, 'icon' | 'color'>>;
		group?: boolean;
		topic?: boolean;
		interactive?: boolean;
		size?: 'sm' | 'md';
		onImage?: boolean;
		onremove?: () => void;
		removeLabel?: string;
	} = $props();

	const path = $derived(pathLabel(tag));
	const nested = $derived(tag.path.length > 1);
	const style = $derived(chipStyle(tag.color));
	const coloured = $derived(style !== null);
</script>

<span
	class={cn(
		// On an image the glass's edge keeps the shape, not the faint ring.
		chipLook(topic ? 'topic' : group ? 'group' : 'tag', tag.color, !onImage),
		// On an image: the same ground, 82 % of it, on glass.
		onImage &&
			cn(
				'mark-glass',
				coloured && !group ? 'bg-(--chip-bg)/82' : group ? 'bg-card/82' : 'bg-secondary/82'
			),
		size === 'sm' ? 'h-6 px-2 text-xs' : 'h-8 pl-3 text-sm',
		size === 'md' && (onremove ? 'pr-1' : 'pr-3')
	)}
	{style}
	title={path}
	data-color={tag.color ?? undefined}
>
	{#if tag.icon}
		<LucideIcon name={tag.icon} class={size === 'sm' ? 'size-3' : 'size-3.5'} />
	{/if}
	{#if interactive && nested}
		<Popover.Root>
			<Popover.Trigger
				class={cn(
					'min-w-0 truncate hover:underline',
					'rounded-full',
					size === 'sm' ? 'max-sm:-my-3.5 max-sm:py-3.5' : 'max-sm:-my-3 max-sm:py-3'
				)}
				aria-label={path}
			>
				{tag.name}
			</Popover.Trigger>
			<Popover.Content class="w-auto max-w-72 px-3 py-2 text-sm" side="top">
				{path}
			</Popover.Content>
		</Popover.Root>
	{:else}
		<span class="min-w-0 truncate">{tag.name}</span>
	{/if}
	{#if onremove}
		<button type="button" class={CHIP_REMOVE} aria-label={removeLabel} onclick={onremove}>
			<X class="size-3.5" aria-hidden="true" />
		</button>
	{/if}
</span>
