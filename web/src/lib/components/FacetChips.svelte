<script lang="ts" module>
	export interface ChipItem {
		id: string;
		label: string;
		/** The tooltip, e.g. the path of a tag. */
		title?: string;
		count: number | null;
		/** A tag's colour (palette name or `#rrggbb`), as its chip shows it elsewhere. */
		color?: string | null;
		icon?: string | null;
	}
</script>

<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import LucideIcon from '#lib/components/LucideIcon.svelte';
	import { chipLook } from '#lib/components/TagChip.svelte';
	import { chipStyle } from '#lib/colors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { flipped } from '#lib/picking.ts';
	import { cn } from '#lib/utils.ts';
	import { Button } from '#lib/components/ui/button/index.ts';

	// Values of the filters as the chips they are everywhere (`chipLook`, as TagChip draws them): a
	// tag round in its colour, a topic square, a group outlined in its colour, a plain value as an
	// uncoloured group; the count in the chip, a chosen one with a tick and a ring. The first
	// `limit` show and the chosen ones; `more` (a label) shows the rest on a tap.
	let {
		items,
		selected,
		onchange,
		look = 'tag',
		label,
		limit = Infinity,
		more
	}: {
		items: readonly ChipItem[];
		selected: readonly string[];
		onchange: (next: string[]) => void;
		look?: 'tag' | 'topic' | 'group' | 'plain';
		/** The name of the group of chips, for screen readers. */
		label: string;
		limit?: number;
		more?: (count: number) => string;
	} = $props();

	let open = $state(false);
	const shown = $derived(
		open ? items : items.filter((item, index) => index < limit || selected.includes(item.id))
	);

	function toggle(id: string) {
		onchange(flipped(selected, id));
	}
</script>

{#if items.length > 0}
	<div class="flex flex-col items-start gap-2">
		<div class="flex flex-wrap gap-1.5" role="group" aria-label={label}>
			{#each shown as item (item.id)}
				{@const color = look === 'plain' ? null : item.color}
				{@const style = chipStyle(color)}
				{@const active = selected.includes(item.id)}
				<button
					type="button"
					aria-pressed={active}
					title={item.title ?? item.label}
					{style}
					class={cn(
						// A chosen chip's own ring takes the place of the faint one.
						chipLook(look === 'plain' ? 'group' : look, color, !active),
						'h-7 px-2.5 text-xs transition-shadow',
						active && 'ring-2 ring-primary ring-offset-2 ring-offset-card',
						active &&
							style === null &&
							(look === 'group' || look === 'plain') &&
							'border-primary bg-panel font-semibold text-brand'
					)}
					onclick={() => toggle(item.id)}
				>
					{#if active}<Check class="size-3 shrink-0" aria-hidden="true" />{/if}
					{#if item.icon}<LucideIcon name={item.icon} class="size-3 shrink-0" />{/if}
					<span class="min-w-0 truncate">{item.label}</span>
					{#if item.count !== null}
						<span class="shrink-0 tabular-nums opacity-70">{formatNumber(item.count)}</span>
					{/if}
				</button>
			{/each}
		</div>
		{#if more && items.length > limit}
			<Button
				variant="link"
				size="inline"
				class="text-sm font-normal"
				aria-expanded={open}
				onclick={() => (open = !open)}
			>
				{open ? m.facet_fewer() : more(items.length)}
			</Button>
		{/if}
	</div>
{/if}
