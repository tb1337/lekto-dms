<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { pageCount, pageSlots } from '#lib/pagination.ts';
	import { m } from '#lib/paraglide/messages.js';

	// Pages of a table (Tobi, 26.10.2026: the jobs; later the documents): which items are shown
	// ("1 – 50 of 1,284"), the page before and after, the page numbers near the current one and
	// the first and the last (`pageSlots`). Nothing of it shows while there is only one page but
	// the count.
	let {
		page,
		total,
		size,
		onchange
	}: {
		/** The current page, from 1. */
		page: number;
		/** How many items there are in all. */
		total: number;
		/** Items per page. */
		size: number;
		onchange: (page: number) => void;
	} = $props();

	const last = $derived(pageCount(total, size));
	const from = $derived(total === 0 ? 0 : (page - 1) * size + 1);
	const to = $derived(Math.min(total, page * size));
	const slots = $derived(pageSlots(page, last));
</script>

<nav
	aria-label={m.pagination_label()}
	class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-[0.8125rem] text-muted-foreground"
>
	<span class="tabular-nums">
		{m.pagination_range({
			from: formatNumber(from),
			to: formatNumber(to),
			total: formatNumber(total)
		})}
	</span>
	{#if last > 1}
		<div class="flex items-center gap-1">
			<Button
				variant="outline"
				size="icon-sm"
				aria-label={m.pagination_previous()}
				disabled={page <= 1}
				onclick={() => onchange(page - 1)}
			>
				<ChevronLeft aria-hidden="true" />
			</Button>
			{#each slots as slot, index (`${slot}-${index}`)}
				{#if typeof slot === 'number'}
					<Button
						variant={slot === page ? 'default' : 'outline'}
						size="icon-sm"
						class="tabular-nums"
						aria-label={m.pagination_page({ page: formatNumber(slot) })}
						aria-current={slot === page ? 'page' : undefined}
						onclick={() => slot !== page && onchange(slot)}
					>
						{formatNumber(slot)}
					</Button>
				{:else}
					<span aria-hidden="true" class="px-1">{slot}</span>
				{/if}
			{/each}
			<Button
				variant="outline"
				size="icon-sm"
				aria-label={m.pagination_next()}
				disabled={page >= last}
				onclick={() => onchange(page + 1)}
			>
				<ChevronRight aria-hidden="true" />
			</Button>
		</div>
	{/if}
</nav>
