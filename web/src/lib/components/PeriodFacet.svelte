<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import type { components } from '#lib/api/schema.ts';
	import { monthPeriod, periodOf, yearPeriod, type Filters } from '#lib/filters.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	type Period = Pick<Filters, 'dateFrom' | 'dateTo'>;

	// The period of the document date: the years with documents, newest first, each with its
	// months to open; one year or one month is chosen, a second tap lets it go. `showCounts`:
	// how many documents each holds (not while searching, the counts know no words).
	let {
		years,
		undated,
		period,
		showCounts,
		onchange
	}: {
		years: readonly components['schemas']['YearCount'][];
		undated: number;
		period: Period;
		showCounts: boolean;
		onchange: (next: Period) => void;
	} = $props();

	const id = $props.id();
	const chosen = $derived(periodOf(period));
	let opened = $state<number[]>([]);
	// A chosen month opens its year.
	const open = $derived(
		chosen?.kind === 'month' ? [...opened, Number(chosen.month.slice(0, 4))] : opened
	);
	const NONE: Period = { dateFrom: null, dateTo: null };

	function monthName(month: string): string {
		const [year, number] = month.split('-').map(Number);
		return formatDate(new Date(year, number - 1, 1), { month: 'long' });
	}

	function toggleYear(year: number) {
		opened = open.includes(year) ? opened.filter((entry) => entry !== year) : [...opened, year];
	}
</script>

{#if years.length > 0}
	<section class="flex flex-col gap-0.5" aria-labelledby="{id}-title">
		<h3
			id="{id}-title"
			class="mb-1 px-2 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
		>
			{m.facet_period()}
		</h3>
		<ul class="flex flex-col">
			{#each years as year (year.year)}
				{@const yearChosen = chosen?.kind === 'year' && chosen.year === year.year}
				{@const expanded = open.includes(year.year)}
				<li>
					<div class="flex items-center">
						<button
							type="button"
							class="grid size-8 shrink-0 place-items-center rounded-lg text-muted-foreground hover:bg-secondary"
							aria-expanded={expanded}
							aria-controls="{id}-{year.year}"
							aria-label={m.facet_months({ year: String(year.year) })}
							onclick={() => toggleYear(year.year)}
						>
							<ChevronRight
								class={['size-4 transition-transform', expanded && 'rotate-90']}
								aria-hidden="true"
							/>
						</button>
						<button
							type="button"
							aria-pressed={yearChosen}
							class={[
								'flex min-h-8 min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1 text-left text-sm transition-colors hover:bg-secondary',
								yearChosen && 'bg-panel font-medium text-brand'
							]}
							onclick={() => onchange(yearChosen ? NONE : yearPeriod(year.year))}
						>
							<span class="flex-1 tabular-nums">{year.year}</span>
							{#if showCounts}
								<span class="text-xs text-muted-foreground tabular-nums">
									{formatNumber(year.count)}
								</span>
							{/if}
						</button>
					</div>
					{#if expanded}
						<ul id="{id}-{year.year}" class="flex flex-col pl-8">
							{#each year.months as month (month.month)}
								{@const monthChosen = chosen?.kind === 'month' && chosen.month === month.month}
								<li>
									<button
										type="button"
										aria-pressed={monthChosen}
										class={[
											'flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-sm transition-colors hover:bg-secondary',
											monthChosen && 'bg-panel font-medium text-brand'
										]}
										onclick={() => onchange(monthChosen ? NONE : monthPeriod(month.month))}
									>
										<span class="flex-1">{monthName(month.month)}</span>
										{#if showCounts}
											<span class="text-xs text-muted-foreground tabular-nums">
												{formatNumber(month.count)}
											</span>
										{/if}
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</li>
			{/each}
		</ul>
		{#if showCounts && undated > 0}
			<p class="px-2 pt-1 text-xs text-muted-foreground">
				{m.facet_undated({ count: formatNumber(undated) })}
			</p>
		{/if}
	</section>
{/if}
