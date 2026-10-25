<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { BarChart } from 'layerchart';
	import { untrack } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { fieldLabel } from '#lib/describe.ts';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import * as Chart from '#lib/components/ui/chart/index.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { latest } from '#lib/latest.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { monthLabel } from '#lib/system.ts';
	import { cn } from '#lib/utils.ts';

	// The tab "Automation" of the page "System" (Tobi, 24.10.2026): how the documents went
	// through their first run, what became of them, how long it took, and how people judged what
	// the automation set at their first decision on a field. For the channels and the period
	// chosen (by default the web and the API, 12 months: migrated documents bring the metadata
	// of the source system); the numbers are the whole system's and name no document.
	type Report = components['schemas']['AutomationOut'];
	type Channel = components['schemas']['Channel'];
	type Period = components['schemas']['Period'];
	type Lane = components['schemas']['Lane'];
	type Field = components['schemas']['FieldVerdictsOut'];

	const CHANNELS: { value: Channel; label: () => string }[] = [
		{ value: 'web', label: m.automation_channel_web },
		{ value: 'api', label: m.automation_channel_api },
		{ value: 'migration', label: m.automation_channel_migration }
	];
	const PERIODS: { value: Period; label: () => string }[] = [
		{ value: '30d', label: m.automation_period_30d },
		{ value: '12m', label: m.automation_period_12m },
		{ value: 'all', label: m.automation_period_all }
	];
	const LANES: { lane: Lane; label: () => string; chip: string; solid: string }[] = [
		{
			lane: 'green',
			label: m.lane_green,
			chip: 'bg-lane-green text-lane-green-foreground ring-lane-green-foreground/35',
			solid: 'bg-chart-1'
		},
		{
			lane: 'yellow',
			label: m.lane_yellow,
			chip: 'bg-lane-yellow text-lane-yellow-foreground ring-lane-yellow-foreground/35',
			solid: 'bg-chart-2'
		},
		{
			lane: 'red',
			label: m.lane_red,
			chip: 'bg-lane-red text-lane-red-foreground ring-lane-red-foreground/35',
			solid: 'bg-chart-3'
		}
	];
	const SOLID: Record<Lane | 'running', string> = {
		green: 'bg-chart-1',
		yellow: 'bg-chart-2',
		red: 'bg-chart-3',
		running: 'bg-muted-foreground/40'
	};
	const SIGNAL_NODES = new Set([
		'signal_llm',
		'signal_classifier',
		'signal_neighbours',
		'signal_facts'
	]);
	const SHOWN_CUSTOM = 3;
	const chartConfig = {
		green: { label: m.lane_green(), color: 'var(--chart-1)' },
		yellow: { label: m.lane_yellow(), color: 'var(--chart-2)' },
		red: { label: m.lane_red(), color: 'var(--chart-3)' }
	} satisfies Chart.ChartConfig;
	const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;

	let channels = $state<Channel[]>(['web', 'api']);
	let period = $state<Period>('12m');
	let report = $state<Report | null>(null);
	let problem = $state<string | null>(null);
	let openCustom = $state(true);
	let allCustom = $state(false);

	// Switching the channels or the period again before the answer came: the newest wins.
	const begin = latest();
	async function load() {
		const current = begin();
		try {
			const found = await unwrap(
				api.GET('/api/v1/automation', {
					params: { query: { channel: [...channels], period, tz: zone } }
				})
			);
			if (!current()) return;
			report = found;
			problem = null;
		} catch (failure) {
			if (!current()) return;
			problem = describeError(failure);
		}
	}
	$effect(() => {
		void channels.join();
		void period;
		untrack(() => void load());
	});

	function toggle(channel: Channel) {
		if (channels.includes(channel)) {
			if (channels.length > 1) channels = channels.filter((item) => item !== channel);
		} else {
			channels = CHANNELS.map((item) => item.value).filter(
				(item) => item === channel || channels.includes(item)
			);
		}
	}

	const percent = (part: number, whole: number) =>
		formatNumber(whole ? part / whole : 0, { style: 'percent', maximumFractionDigits: 0 });
	const duration = (ms: number | null | undefined) =>
		ms == null ? '–' : formatDuration(ms / 1000);
	const list = (items: string[]) =>
		new Intl.ListFormat(document.documentElement.lang || undefined, { type: 'conjunction' }).format(
			items
		);

	const total = $derived(report ? report.lanes.green + report.lanes.yellow + report.lanes.red : 0);
	const scope = $derived(
		report
			? m.automation_first_scope({
					count: formatNumber(total),
					channels: list(
						CHANNELS.filter((item) => report?.channels.includes(item.value)).map((item) =>
							item.label()
						)
					),
					period: PERIODS.find((item) => item.value === report?.period)?.label() ?? ''
				})
			: ''
	);

	// What became of the documents of each first lane: their lanes now.
	const flows = $derived(
		report
			? LANES.map(({ lane, label, chip }) => {
					const parts = report!.flow.filter((item) => item.first_lane === lane);
					const count = parts.reduce((sum, item) => sum + item.count, 0);
					return {
						lane,
						label,
						chip,
						count,
						parts: parts.map((item) => ({
							key: (item.lane ?? 'running') as Lane | 'running',
							count: item.count,
							text: flowText(lane, item.lane, item.count)
						}))
					};
				}).filter((item) => item.count > 0)
			: []
	);

	function flowText(first: Lane, now: Lane | null, count: number): string {
		const n = formatNumber(count);
		if (now === null) return m.automation_flow_running({ count: n });
		if (now === first && first !== 'green') return m.automation_flow_open({ count: n });
		if (now === 'green') return m.automation_flow_done({ count: n });
		if (now === 'yellow') return m.automation_flow_review({ count: n });
		return m.automation_flow_failed({ count: n });
	}

	// The months by their first day (unique: a month name alone names two in twenty months),
	// labelled with the year once the history spans more than one.
	const months = $derived.by(() => {
		const found = report?.months ?? [];
		const years = new Set(found.map((month) => month.start.slice(0, 4)));
		return found.map((month) => ({
			start: month.start,
			label: monthLabel(month.start, years.size > 1),
			...month.lanes
		}));
	});
	const monthLabels = $derived(new Map(months.map((month) => [month.start, month.label])));
	const labelOf = (start: string) => monthLabels.get(start) ?? start;
	const shares = $derived(
		(report?.months ?? [])
			.map((month) => month.lanes)
			.filter((lanes) => lanes.green + lanes.yellow + lanes.red > 0)
			.map((lanes) => lanes.green / (lanes.green + lanes.yellow + lanes.red))
	);

	const decided = (field: Field) =>
		field.verdicts.taken +
		field.verdicts.accepted +
		field.verdicts.corrected +
		field.verdicts.added;
	const hits = (field: Field) => field.verdicts.taken + field.verdicts.accepted;
	const counts = (field: Field) =>
		m.automation_field_counts({
			taken: formatNumber(field.verdicts.taken),
			accepted: formatNumber(field.verdicts.accepted),
			corrected: formatNumber(field.verdicts.corrected),
			added: formatNumber(field.verdicts.added)
		});
	const fixed = $derived((report?.fields ?? []).filter((item) => !item.name && decided(item) > 0));
	const custom = $derived((report?.fields ?? []).filter((item) => item.name && decided(item) > 0));
	const customTotal = $derived(
		custom.reduce(
			(sum, item) => ({
				field: 'custom',
				name: null,
				early: 0,
				verdicts: {
					taken: sum.verdicts.taken + item.verdicts.taken,
					accepted: sum.verdicts.accepted + item.verdicts.accepted,
					corrected: sum.verdicts.corrected + item.verdicts.corrected,
					added: sum.verdicts.added + item.verdicts.added
				}
			}),
			{
				field: 'custom',
				name: null,
				early: 0,
				verdicts: { taken: 0, accepted: 0, corrected: 0, added: 0 }
			} as Field
		)
	);
	const early = $derived((report?.fields ?? []).reduce((sum, item) => sum + item.early, 0));

	const longest = $derived(Math.max(1, ...(report?.steps ?? []).map((step) => step.p90_ms ?? 0)));
	const width = (ms: number | null, least: number) =>
		`${Math.max(least, (100 * (ms ?? 0)) / longest).toFixed(1)}%`;
</script>

{#snippet verdictBar(field: Field, height: string)}
	<div
		role="img"
		aria-label={counts(field)}
		class={cn('flex gap-0.5 overflow-hidden rounded-full', height)}
	>
		<div class="bg-chart-1" style:flex="{field.verdicts.taken} 1 0"></div>
		<div
			class="bg-lane-green ring-1 ring-lane-green-foreground/35 ring-inset"
			style:flex="{field.verdicts.accepted} 1 0"
		></div>
		<div class="bg-chart-3" style:flex="{field.verdicts.corrected} 1 0"></div>
		<div
			class="bg-lane-yellow ring-1 ring-lane-yellow-foreground/35 ring-inset"
			style:flex="{field.verdicts.added} 1 0"
		></div>
	</div>
{/snippet}

{#snippet swatch(kind: string, label: string)}
	<span class="inline-flex items-center gap-1.5">
		<span aria-hidden="true" class={cn('size-3 rounded-[3px]', kind)}></span>{label}
	</span>
{/snippet}

<div class="flex flex-col gap-6">
	<div class="flex flex-wrap items-center gap-x-7 gap-y-3">
		<div role="group" aria-label={m.automation_channel()} class="flex flex-wrap items-center gap-2">
			<span class="text-[0.8125rem] text-muted-foreground">{m.automation_channel()}</span>
			{#each CHANNELS as item (item.value)}
				{@const on = channels.includes(item.value)}
				<button
					type="button"
					aria-pressed={on}
					onclick={() => toggle(item.value)}
					class={cn(
						'inline-flex h-11 items-center gap-1.5 rounded-full border px-3.5 text-[0.8125rem] sm:h-[34px]',
						on
							? 'border-primary bg-panel font-medium text-primary'
							: 'bg-card text-muted-foreground hover:text-foreground'
					)}
				>
					{#if on}<Check class="size-3.5" aria-hidden="true" />{/if}{item.label()}
				</button>
			{/each}
		</div>
		<div role="group" aria-label={m.automation_period()} class="flex items-center gap-2">
			<span class="text-[0.8125rem] text-muted-foreground">{m.automation_period()}</span>
			<div class="flex gap-0.5 rounded-full bg-muted p-[3px]">
				{#each PERIODS as item (item.value)}
					<button
						type="button"
						aria-pressed={period === item.value}
						onclick={() => (period = item.value)}
						class={cn(
							'h-10 rounded-full px-3 text-[0.8125rem] sm:h-[30px]',
							period === item.value
								? 'bg-card font-medium text-foreground shadow-xs'
								: 'text-muted-foreground hover:text-foreground'
						)}
					>
						{item.label()}
					</button>
				{/each}
			</div>
		</div>
	</div>

	{#if problem && !report}
		<LoadProblem {problem} onretry={load} />
	{:else if !report}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<div class="flex flex-wrap gap-6">
			<section
				class="flex min-w-0 flex-[2_1_520px] flex-col gap-4 rounded-2xl border bg-card px-5 py-4 sm:px-6"
			>
				<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
					<h2 class="font-semibold">{m.automation_first_title()}</h2>
					<span class="text-[0.8125rem] text-muted-foreground">{scope}</span>
				</div>
				{#if total === 0}
					<p class="text-muted-foreground">{m.automation_none()}</p>
				{:else}
					<div
						role="img"
						aria-label={m.automation_first_bar({
							green: percent(report.lanes.green, total),
							yellow: percent(report.lanes.yellow, total),
							red: percent(report.lanes.red, total)
						})}
						class="flex h-3.5 gap-[3px] overflow-hidden rounded-full"
					>
						{#each LANES as { lane, solid } (lane)}
							<div class={solid} style:flex="{report.lanes[lane]} 1 0"></div>
						{/each}
					</div>
					<div class="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-4">
						{#each LANES as { lane, label, chip } (lane)}
							<div class="flex flex-col gap-1">
								<span
									class={cn(
										'inline-flex h-6 items-center self-start rounded-full px-2.5 text-xs font-medium ring-1 ring-inset',
										chip
									)}
								>
									{label()}
								</span>
								<span class="text-[1.875rem] font-semibold tracking-tight tabular-nums">
									{percent(report.lanes[lane], total)}
								</span>
								<span class="text-[0.8125rem] text-muted-foreground">
									{(
										{
											green: m.automation_first_green,
											yellow: m.automation_first_yellow,
											red: m.automation_first_red
										} as const
									)[lane]({ count: formatNumber(report.lanes[lane]) })}
								</span>
							</div>
						{/each}
					</div>
				{/if}
			</section>

			<section
				class="flex min-w-0 flex-[1_1_260px] flex-col rounded-2xl border bg-card px-5 py-4 sm:px-6"
			>
				<h2 class="font-semibold">{m.automation_duration_title()}</h2>
				<span class="text-[0.8125rem] text-muted-foreground">{m.automation_duration_hint()}</span>
				<div class="mt-4 flex items-baseline gap-2">
					<span class="text-[1.875rem] font-semibold tracking-tight tabular-nums">
						{duration(report.duration.median_ms)}
					</span>
					<span class="text-[0.8125rem] text-muted-foreground">{m.automation_median()}</span>
				</div>
				<span class="text-[0.8125rem] text-muted-foreground">
					{m.automation_duration_p90({ duration: duration(report.duration.p90_ms) })}
				</span>
				<div aria-hidden="true" class="my-4 h-px bg-border"></div>
				<div class="flex items-baseline gap-2">
					<span class="text-xl font-semibold tabular-nums">{duration(report.work.median_ms)}</span>
					<span class="text-[0.8125rem] text-muted-foreground">{m.automation_work()}</span>
				</div>
				<span class="text-[0.8125rem] text-muted-foreground">
					{m.automation_work_p90({ duration: duration(report.work.p90_ms) })}
				</span>
			</section>
		</div>

		{#if flows.length}
			<section class="rounded-2xl border bg-card px-5 py-4 sm:px-6">
				<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
					<h2 class="font-semibold">{m.automation_flow_title()}</h2>
					<span class="text-[0.8125rem] text-muted-foreground">{m.automation_flow_hint()}</span>
				</div>
				<div class="mt-4 flex flex-col gap-4">
					{#each flows as flow (flow.lane)}
						{@const caption = flow.parts.map((part) => part.text).join(' · ')}
						<div class="grid grid-cols-1 items-start gap-x-5 gap-y-2 sm:grid-cols-[170px_1fr]">
							<div class="flex h-6 items-center gap-2">
								<span
									class={cn(
										'inline-flex h-6 items-center rounded-full px-2.5 text-xs font-medium ring-1 ring-inset',
										flow.chip
									)}
								>
									{flow.label()}
								</span>
								<span class="font-semibold tabular-nums">{formatNumber(flow.count)}</span>
								<ArrowRight class="size-4 text-muted-foreground" aria-hidden="true" />
							</div>
							<div class="flex flex-col gap-1.5 pt-[7px]">
								<div
									role="img"
									aria-label={caption}
									class="flex h-2.5 gap-[3px] overflow-hidden rounded-full"
								>
									{#each flow.parts as part (part.key)}
										<div class={SOLID[part.key]} style:flex="{part.count} 1 0"></div>
									{/each}
								</div>
								<span class="text-[0.8125rem] text-muted-foreground">{caption}</span>
							</div>
						</div>
					{/each}
				</div>
			</section>
		{/if}

		<section class="rounded-2xl border bg-card px-5 py-4 sm:px-6">
			<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
				<h2 class="font-semibold">{m.automation_months_title()}</h2>
				<span class="text-[0.8125rem] text-muted-foreground">
					{#if shares.length > 1}
						{m.automation_months_share({
							from: percent(shares[0], 1),
							to: percent(shares[shares.length - 1], 1)
						})}
					{:else if report.period === '30d'}
						{m.automation_months_last()}
					{/if}
				</span>
			</div>
			<div class="mt-3 flex flex-wrap gap-4 text-[0.8125rem] text-muted-foreground">
				{#each LANES as { lane, label, solid } (lane)}
					{@render swatch(solid, label())}
				{/each}
			</div>
			<div role="img" aria-label={m.automation_months_label()} class="mt-3">
				<Chart.Container config={chartConfig} class="aspect-auto h-[200px] w-full">
					<BarChart
						data={months}
						x="start"
						axis
						grid={{ y: true, x: false }}
						rule={false}
						seriesLayout="stack"
						series={LANES.map(({ lane }) => ({
							key: lane,
							label: chartConfig[lane].label,
							color: chartConfig[lane].color
						}))}
						props={{
							bars: { stroke: 'none' },
							xAxis: { format: labelOf },
							yAxis: { ticks: 4, format: formatNumber },
							// Its sum is labelled in English only.
							tooltip: { hideTotal: true, header: { format: labelOf } }
						}}
					/>
				</Chart.Container>
			</div>
		</section>

		<section class="rounded-2xl border bg-card px-5 py-4 sm:px-6">
			<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
				<h2 class="font-semibold">{m.automation_hits_title()}</h2>
				<span class="text-[0.8125rem] text-muted-foreground">{m.automation_hits_hint()}</span>
			</div>
			<p class="mt-2 max-w-3xl text-[0.8125rem] text-muted-foreground">
				{m.automation_hits_text({
					decided: formatNumber(report.decided),
					untouched: formatNumber(report.untouched)
				})}
				{#if early}
					<span>{m.automation_hits_early({ count: formatNumber(early) })}</span>
				{/if}
			</p>
			{#if !fixed.length && !custom.length}
				<p class="mt-3 text-muted-foreground">{m.automation_hits_none()}</p>
			{:else}
				<div
					class="mt-3.5 flex flex-wrap gap-x-[18px] gap-y-2 text-[0.8125rem] text-muted-foreground"
				>
					{@render swatch('bg-chart-1', m.automation_verdict_taken())}
					{@render swatch(
						'bg-lane-green ring-1 ring-lane-green-foreground/35 ring-inset',
						m.automation_verdict_accepted()
					)}
					{@render swatch('bg-chart-3', m.automation_verdict_corrected())}
					{@render swatch(
						'bg-lane-yellow ring-1 ring-lane-yellow-foreground/35 ring-inset',
						m.automation_verdict_added()
					)}
				</div>
				<div
					class="mt-5 grid grid-cols-[repeat(auto-fit,minmax(min(400px,100%),1fr))] gap-x-10 gap-y-[22px]"
				>
					{#each fixed as field (field.field)}
						<div class="flex min-w-0 flex-col gap-1.5">
							<div class="flex items-baseline justify-between gap-3">
								<span class="font-medium">
									{fieldLabel(field.field, null)}
									<span class="text-xs font-normal text-muted-foreground">
										{m.automation_field_decided({ count: formatNumber(decided(field)) })}
									</span>
								</span>
								<span class="font-semibold tabular-nums">
									{percent(hits(field), decided(field))}
									<span class="text-xs font-normal text-muted-foreground">
										{m.automation_field_hit()}
									</span>
								</span>
							</div>
							{@render verdictBar(field, 'h-3')}
							<span class="text-xs text-muted-foreground tabular-nums">{counts(field)}</span>
						</div>
					{/each}
				</div>
				{#if custom.length}
					<div class="mt-[22px] flex flex-col gap-3.5 border-t pt-[18px]">
						<div class="flex flex-col gap-1.5">
							<div class="flex items-center justify-between gap-3">
								<button
									type="button"
									aria-expanded={openCustom}
									onclick={() => (openCustom = !openCustom)}
									class="inline-flex min-h-11 items-center gap-1.5 text-left font-medium sm:min-h-0"
								>
									<ChevronDown
										class={cn('size-4 transition-transform', !openCustom && '-rotate-90')}
										aria-hidden="true"
									/>
									{m.automation_custom_fields()}
									<span class="text-xs font-normal text-muted-foreground">
										{m.automation_custom_decided({
											count: formatNumber(decided(customTotal)),
											fields: formatNumber(custom.length)
										})}
									</span>
								</button>
								<span class="font-semibold tabular-nums">
									{percent(hits(customTotal), decided(customTotal))}
									<span class="text-xs font-normal text-muted-foreground">
										{m.automation_field_hit()}
									</span>
								</span>
							</div>
							{@render verdictBar(customTotal, 'h-3')}
						</div>
						{#if openCustom}
							<div
								class="grid grid-cols-[repeat(auto-fit,minmax(min(280px,100%),1fr))] gap-x-8 gap-y-4 pl-[22px]"
							>
								{#each allCustom ? custom : custom.slice(0, SHOWN_CUSTOM) as field (field.field)}
									<div class="flex min-w-0 flex-col gap-[5px]">
										<div class="flex items-baseline justify-between gap-3 text-[0.8125rem]">
											<span class="min-w-0 truncate">
												{field.name}
												<span class="text-xs text-muted-foreground">
													{formatNumber(decided(field))}
												</span>
											</span>
											<span class="font-semibold tabular-nums">
												{percent(hits(field), decided(field))}
											</span>
										</div>
										{@render verdictBar(field, 'h-2')}
									</div>
								{/each}
							</div>
							{#if custom.length > SHOWN_CUSTOM}
								<button
									type="button"
									onclick={() => (allCustom = !allCustom)}
									class="min-h-11 self-start pl-[22px] text-[0.8125rem] text-primary hover:underline sm:min-h-0"
								>
									{allCustom
										? m.automation_custom_fewer()
										: m.automation_custom_more({
												count: formatNumber(custom.length - SHOWN_CUSTOM)
											})}
								</button>
							{/if}
						{/if}
					</div>
				{/if}
			{/if}
		</section>

		{#if report.steps.length}
			<section class="rounded-2xl border bg-card px-5 py-4 sm:px-6">
				<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
					<h2 class="font-semibold">{m.automation_steps_title()}</h2>
					<span class="text-[0.8125rem] text-muted-foreground">{m.automation_steps_hint()}</span>
				</div>
				<div
					class="mt-3 flex flex-wrap gap-x-[18px] gap-y-2 text-[0.8125rem] text-muted-foreground"
				>
					<span class="inline-flex items-center gap-1.5">
						<span aria-hidden="true" class="h-2 w-4 rounded-full bg-primary"></span>
						{m.automation_median()}
					</span>
					<span class="inline-flex items-center gap-1.5">
						<span aria-hidden="true" class="h-2 w-4 rounded-full bg-chart-5"></span>
						{m.automation_to_p90()}
					</span>
				</div>
				<div class="mt-4 flex flex-col gap-2.5">
					{#each report.steps as step, index (step.node)}
						{@const signal = SIGNAL_NODES.has(step.node)}
						{#if signal && !SIGNAL_NODES.has(report.steps[index - 1]?.node ?? '')}
							<span
								class="mt-1.5 text-xs font-medium tracking-[0.04em] text-muted-foreground uppercase"
							>
								{m.automation_steps_signals()}
							</span>
						{/if}
						<div
							class="grid grid-cols-[104px_1fr_96px] items-center gap-3 sm:grid-cols-[170px_1fr_130px]"
						>
							<span class={cn('text-[0.8125rem]', signal && 'border-l-2 pl-3')}>
								{NODE_LABELS[step.node]()}
							</span>
							<div class="relative h-2.5 rounded-full bg-muted">
								<div
									class="absolute inset-y-0 left-0 rounded-full bg-chart-5"
									style:width={width(step.p90_ms, 1.2)}
								></div>
								<div
									class="absolute inset-y-0 left-0 rounded-full bg-primary"
									style:width={width(step.median_ms, 0.8)}
								></div>
							</div>
							<span class="text-right text-[0.8125rem] whitespace-nowrap tabular-nums">
								{duration(step.median_ms)}
								<span class="text-muted-foreground"
									>{m.automation_step_p90({ duration: duration(step.p90_ms) })}</span
								>
							</span>
						</div>
					{/each}
				</div>
			</section>
		{/if}
	{/if}
</div>
