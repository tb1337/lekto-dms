<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { formatNumber } from '#lib/i18n.ts';
	import { PAGE_SIZES, rememberPageSize, type PagedTable } from '#lib/page-size.ts';
	import { pageCount, pageSlots } from '#lib/pagination.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';
	import IconButton from '#lib/components/IconButton.svelte';
	import { buttonVariants } from '#lib/components/ui/button/index.ts';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.ts';

	// Pages of a table (Tobi, 26.10.2026: the jobs; later the documents): which items are shown
	// ("1 – 50 of 1,284"), the page before and after, the page numbers near the current one and
	// the first and the last (`pageSlots`). Nothing of it shows while there is only one page but
	// the count. A `table` offers its page sizes in a small menu beside the count, while there
	// are more items than the smallest size; the choice is remembered for that table wherever
	// it shows (`page-size.ts`; Tobi, 27.10.2026).
	let {
		page,
		total,
		size,
		table,
		onchange,
		onsize
	}: {
		/** The current page, from 1. */
		page: number;
		/** How many items there are in all. */
		total: number;
		/** Items per page. */
		size: number;
		/** The table whose page sizes to offer; none offers no choice. */
		table?: PagedTable;
		onchange: (page: number) => void;
		/** Called with the size the person chose, after it is remembered. */
		onsize?: (size: number) => void;
	} = $props();

	const last = $derived(pageCount(total, size));
	const from = $derived(total === 0 ? 0 : (page - 1) * size + 1);
	const to = $derived(Math.min(total, page * size));
	const slots = $derived(pageSlots(page, last));
	const sizes = $derived(table ? PAGE_SIZES[table] : []);

	function choose(value: string) {
		const next = Number(value);
		if (!table || next === size) return;
		rememberPageSize(table, next);
		onsize?.(next);
	}
</script>

<nav
	aria-label={m.pagination_label()}
	class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-meta text-muted-foreground"
>
	<div class="flex items-center gap-3">
		<span class="tabular-nums">
			{m.pagination_range({
				from: formatNumber(from),
				to: formatNumber(to),
				total: formatNumber(total)
			})}
		</span>
		{#if sizes.length > 0 && total > Math.min(...sizes)}
			<DropdownMenu.Root>
				<DropdownMenu.Trigger
					class={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'tabular-nums')}
				>
					{m.pagination_size({ size: formatNumber(size) })}
					<ChevronDown class="text-muted-foreground" aria-hidden="true" />
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="start" class="w-48">
					<DropdownMenu.RadioGroup
						value={String(size)}
						onValueChange={choose}
						aria-label={m.pagination_size_label()}
					>
						{#each sizes as option (option)}
							<DropdownMenu.RadioItem value={String(option)} class="tabular-nums">
								{m.pagination_size({ size: formatNumber(option) })}
							</DropdownMenu.RadioItem>
						{/each}
					</DropdownMenu.RadioGroup>
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		{/if}
	</div>
	{#if last > 1}
		<div class="flex items-center gap-1">
			<IconButton
				variant="outline"
				size="sm"
				label={m.pagination_previous()}
				disabled={page <= 1}
				onclick={() => onchange(page - 1)}
			>
				<ChevronLeft aria-hidden="true" />
			</IconButton>
			{#each slots as slot, index (`${slot}-${index}`)}
				{#if typeof slot === 'number'}
					<IconButton
						variant={slot === page ? 'default' : 'outline'}
						size="sm"
						class="tabular-nums"
						label={m.pagination_page({ page: formatNumber(slot) })}
						aria-current={slot === page ? 'page' : undefined}
						onclick={() => slot !== page && onchange(slot)}
					>
						{formatNumber(slot)}
					</IconButton>
				{:else}
					<span aria-hidden="true" class="px-1">{slot}</span>
				{/if}
			{/each}
			<IconButton
				variant="outline"
				size="sm"
				label={m.pagination_next()}
				disabled={page >= last}
				onclick={() => onchange(page + 1)}
			>
				<ChevronRight aria-hidden="true" />
			</IconButton>
		</div>
	{/if}
</nav>
