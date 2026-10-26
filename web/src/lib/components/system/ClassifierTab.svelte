<script lang="ts">
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import { LineChart, Spline } from 'layerchart';
	import { onMount, untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import type { components } from '#lib/api/schema.ts';
	import { fieldLabel } from '#lib/describe.ts';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import * as Chart from '#lib/components/ui/chart/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';

	// The tab "Classifier" of the page "System" (Tobi, 24.10.2026): what the latest model
	// learned and how well, how far the next training is, how the models got better, and how
	// often each signal named the value a person decided (web and API, 12 months). Every user
	// sees it; training on request is for admins (it also trains on its own).
	type Status = components['schemas']['ClassifierStatusOut'];
	type Model = components['schemas']['ClassifierModelOut'];
	type Signals = components['schemas']['SignalsOut'];
	type Node = components['schemas']['Node'];

	const SIGNALS: Node[] = ['signal_llm', 'signal_classifier', 'signal_neighbours', 'signal_facts'];
	const FIELDS = ['contact', 'document_type', 'topic', 'space', 'document_date'];
	const chartConfig = {
		contact: { label: m.field_contact(), color: 'var(--primary)' },
		document_type: { label: m.field_document_type(), color: 'var(--chart-4)' }
	} satisfies Chart.ChartConfig;
	const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;

	let status = $state<Status | null>(null);
	let models = $state<Model[]>([]);
	let signals = $state<Signals | null>(null);
	let unavailable = $state(false);
	let problem = $state<string | null>(null);
	let busy = $state(false);

	async function load() {
		try {
			[status, models, signals] = await Promise.all([
				unwrap(api.GET('/api/v1/classifier')),
				unwrap(api.GET('/api/v1/classifier/models')),
				unwrap(api.GET('/api/v1/automation/signals', { params: { query: { tz: zone } } }))
			]);
			problem = null;
		} catch (failure) {
			if (failure instanceof ApiError && failure.status === 503) unavailable = true;
			else problem = describeError(failure);
		}
	}
	// Again after a break of the stream: the end of a training may have been missed.
	$effect(() => {
		void events.generation;
		untrack(() => void load());
	});

	// A training runs in the background: its model shows once it is stored.
	onMount(() =>
		events.on('classifier.trained', (event) => {
			toast.success(m.classifier_trained({ number: String(event.number) }));
			void load();
		})
	);

	async function train() {
		if (busy) return;
		busy = true;
		try {
			await unwrap(api.POST('/api/v1/classifier/train'));
			toast.success(m.classifier_train_queued());
		} catch (failure) {
			toast.error(describeError(failure));
		} finally {
			busy = false;
		}
	}

	const percent = (value: number | null | undefined) =>
		value == null ? '–' : formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });
	const when = (value: string) => formatDate(value, { dateStyle: 'medium', timeStyle: 'short' });

	const measured = $derived(
		models
			.filter((model) => model.accuracy?.contact != null || model.accuracy?.document_type != null)
			.map((model) => ({
				number: model.number,
				examples: model.examples,
				contact: model.accuracy?.contact ?? null,
				document_type: model.accuracy?.document_type ?? null
			}))
	);
	const latestMeasured = $derived(measured.at(-1));
	// The axis from a tenth below the weakest measurement; at most eight models named on it.
	const floor = $derived(
		Math.max(
			0,
			Math.floor(
				Math.min(
					1,
					...measured.flatMap((model) => [model.contact ?? 1, model.document_type ?? 1])
				) * 10
			) /
				10 -
				0.1
		)
	);
	const ticks = $derived(
		measured
			.filter(
				(_, index) => index % Math.ceil(measured.length / 8) === 0 || index === measured.length - 1
			)
			.map((model) => model.number)
	);
	const tickLabel = (number: number) => {
		const model = measured.find((item) => item.number === number);
		return model
			? `${m.classifier_history_model({ number })}\n${m.classifier_history_examples({ count: formatNumber(model.examples) })}`
			: m.classifier_history_model({ number });
	};
	// Towards the next training, or the first model.
	const done = $derived(status ? (status.model ? status.since : status.confirmed) : 0);
	const needed = $derived(status ? (status.model ? status.retrain_after : status.min_examples) : 1);

	// Per signal and field: the share of its hits among the decisions it named a value in, and
	// the best signal of each field.
	const table = $derived.by(() => {
		const found = new Map(
			(signals?.signals ?? []).map((item) => [`${item.signal} ${item.field}`, item])
		);
		const rate = (signal: Node, field: string) => {
			const item = found.get(`${signal} ${field}`);
			const named = item ? item.hits + item.misses : 0;
			return item && named ? { share: item.hits / named, named, decided: item.decided } : null;
		};
		const best = Object.fromEntries(
			FIELDS.map((field) => {
				const shares = SIGNALS.map((signal) => rate(signal, field)?.share ?? -1);
				const top = Math.max(...shares);
				return [field, top >= 0 ? SIGNALS[shares.indexOf(top)] : null];
			})
		);
		return SIGNALS.map((signal) => ({
			signal,
			cells: FIELDS.map((field) => ({
				field,
				rate: rate(signal, field),
				best: best[field] === signal
			}))
		}));
	});
	const anySignal = $derived((signals?.signals ?? []).some((item) => item.hits + item.misses > 0));
</script>

{#snippet heading(text: string, about: string)}
	<div class="flex items-center gap-1">
		<SectionTitle size="card">{text}</SectionTitle>
		<InfoTip label={m.hint_about({ name: text })} size="sm" class="w-80">
			<p>{about}</p>
		</InfoTip>
	</div>
{/snippet}

<div class="flex flex-col gap-6">
	{#if unavailable}
		<p class="text-muted-foreground">{m.classifier_not_configured()}</p>
	{:else if problem && !status}
		<LoadProblem {problem} onretry={load} />
	{:else if !status}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<div class="flex flex-wrap gap-6">
			<Card.Root as="section" size="lg" class="flex min-w-0 flex-[2_1_560px] flex-col gap-[18px]">
				<div class="flex flex-wrap items-start justify-between gap-3">
					<div class="flex flex-col gap-0.5">
						{#if status.model}
							{@const model = status.model}
							{@render heading(
								m.classifier_model_title({ number: model.number }),
								m.classifier_model_info()
							)}
							<span class="text-meta text-muted-foreground">
								{model.examples_until
									? m.classifier_model_trained_until({
											date: when(model.trained_at),
											examples: formatNumber(model.examples),
											until: formatDate(model.examples_until, {
												day: 'numeric',
												month: 'numeric',
												hour: '2-digit',
												minute: '2-digit'
											})
										})
									: m.classifier_model_trained({
											date: when(model.trained_at),
											examples: formatNumber(model.examples)
										})}
							</span>
						{:else}
							{@render heading(m.classifier_no_model(), m.classifier_model_info())}
						{/if}
					</div>
					{#if session.isAdmin}
						<Button onclick={train} disabled={busy}>
							<RefreshCw aria-hidden="true" />{m.classifier_train()}
						</Button>
					{/if}
				</div>
				{#if status.model}
					{@const model = status.model}
					<div class="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-3">
						{#each [[model.classes.contact, m.classifier_class_contacts()], [model.classes.document_type, m.classifier_class_types()], [model.classes.topic, m.classifier_class_topics()], [model.classes.tags, m.classifier_class_tags()], [model.classes.space, m.classifier_class_spaces()], [model.learned_identifiers, m.classifier_class_identifiers()]] as const as [count, label] (label)}
							<div class="flex flex-col gap-0.5 rounded-xl bg-surface px-3.5 py-3">
								<span class="text-2xl font-semibold tracking-tight tabular-nums">
									{formatNumber(count)}
								</span>
								<span class="text-meta text-muted-foreground">{label}</span>
							</div>
						{/each}
					</div>
					{#if model.accuracy}
						{@const accuracy = model.accuracy}
						<div class="flex flex-col gap-2.5">
							<span class="text-meta text-muted-foreground">
								{m.classifier_tested({ tested: formatNumber(accuracy.tested) })}
							</span>
							{#each [[m.field_contact(), accuracy.contact], [m.field_document_type(), accuracy.document_type]] as const as [label, value] (label)}
								<div class="grid grid-cols-[120px_1fr_48px] items-center gap-3">
									<span class="text-meta">{label}</span>
									<div
										role="progressbar"
										aria-label={label}
										aria-valuemin={0}
										aria-valuemax={100}
										aria-valuenow={Math.round((value ?? 0) * 100)}
										class="h-2.5 overflow-hidden rounded-full bg-muted"
									>
										<div
											class="h-full rounded-full bg-primary"
											style:width="{(value ?? 0) * 100}%"
										></div>
									</div>
									<span class="text-right font-semibold tabular-nums">{percent(value)}</span>
								</div>
							{/each}
						</div>
					{:else}
						<span class="text-meta text-muted-foreground">
							{m.classifier_accuracy_none()}
						</span>
					{/if}
					{#if model.method}
						<span class="font-mono text-xs text-muted-foreground">{model.method}</span>
					{/if}
				{/if}
			</Card.Root>

			<Card.Root as="section" size="lg" class="flex min-w-0 flex-[1_1_280px] flex-col gap-3">
				{@render heading(m.classifier_next_title(), m.classifier_next_info())}
				<div class="flex items-baseline gap-2">
					<span class="text-figure tabular-nums">
						{formatNumber(done)}
					</span>
					<span class="text-muted-foreground">
						{m.classifier_next_of({ needed: formatNumber(needed) })}
					</span>
				</div>
				<div
					role="progressbar"
					aria-label={m.classifier_next_label()}
					aria-valuemin={0}
					aria-valuemax={needed}
					aria-valuenow={Math.min(done, needed)}
					class="h-2.5 overflow-hidden rounded-full bg-muted"
				>
					<div
						class="h-full rounded-full bg-primary"
						style:width="{Math.min(100, (100 * done) / Math.max(1, needed))}%"
					></div>
				</div>
				<span class="text-meta text-muted-foreground">
					{status.model
						? m.classifier_next_text({ number: status.model.number })
						: m.classifier_first_text()}
				</span>
				<div aria-hidden="true" class="my-1 h-px bg-border"></div>
				<span class="text-meta text-muted-foreground">
					{m.classifier_confirmed_total({ count: formatNumber(status.confirmed) })}
				</span>
				<span class="text-meta text-muted-foreground">
					{m.classifier_threshold({ threshold: percent(status.threshold) })}
				</span>
			</Card.Root>
		</div>

		<Card.Root as="section" size="lg">
			<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
				{@render heading(m.classifier_history_title(), m.classifier_history_info())}
				<span class="text-meta text-muted-foreground">{m.classifier_history_hint()}</span>
			</div>
			{#if measured.length < 2}
				<p class="mt-3 text-muted-foreground">{m.classifier_history_none()}</p>
			{:else}
				<div class="mt-3 flex flex-wrap gap-x-[18px] gap-y-2 text-meta text-muted-foreground">
					<span class="inline-flex items-center gap-1.5">
						<span aria-hidden="true" class="w-[18px] border-t-[2.5px] border-primary"></span>
						{m.field_contact()}
						{#if latestMeasured}
							<span class="font-semibold text-brand">{percent(latestMeasured.contact)}</span>
						{/if}
					</span>
					<span class="inline-flex items-center gap-1.5">
						<span aria-hidden="true" class="w-[18px] border-t-[2.5px] border-dashed border-chart-4"
						></span>
						{m.field_document_type()}
						{#if latestMeasured}
							<span class="font-semibold text-chart-4">
								{percent(latestMeasured.document_type)}
							</span>
						{/if}
					</span>
				</div>
				<div role="img" aria-label={m.classifier_history_label()} class="mt-3">
					<Chart.Container config={chartConfig} class="aspect-auto h-[220px] w-full">
						<LineChart
							data={measured}
							x="number"
							axis
							yDomain={[floor, 1]}
							padding={{ top: 8, left: 48, right: 56, bottom: 40 }}
							points={{ r: 4 }}
							series={[
								{
									key: 'contact',
									label: chartConfig.contact.label,
									color: chartConfig.contact.color
								},
								{
									key: 'document_type',
									label: chartConfig.document_type.label,
									color: chartConfig.document_type.color
								}
							]}
							props={{
								xAxis: {
									ticks: ticks,
									format: (value: number) => tickLabel(value),
									tickMultiline: true,
									tickOcclusion: { priority: 'start-end', padding: 8 }
								},
								// The floor's label would touch the name of the first model below it.
								yAxis: {
									ticks: 4,
									format: (value: number) => (value === floor ? '' : percent(value))
								}
							}}
						>
							{#snippet marks({ context })}
								{#each context.series.visibleSeries as line (line.key)}
									<Spline
										seriesKey={line.key}
										strokeWidth={2.5}
										stroke-dasharray={line.key === 'document_type' ? '6 4' : undefined}
									/>
								{/each}
							{/snippet}
						</LineChart>
					</Chart.Container>
				</div>
			{/if}
		</Card.Root>

		<Card.Root as="section" size="lg">
			<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
				{@render heading(m.classifier_signals_title(), m.classifier_signals_info())}
				<span class="text-meta text-muted-foreground">{m.classifier_signals_hint()}</span>
			</div>
			{#if !anySignal}
				<p class="mt-3 text-muted-foreground">{m.classifier_signals_none()}</p>
			{:else}
				<div class="mt-4 overflow-x-auto">
					<table class="w-full min-w-[720px] border-collapse tabular-nums">
						<thead>
							<tr>
								<th
									scope="col"
									class="border-b pr-3 pb-2.5 text-left text-xs font-medium text-muted-foreground"
								>
									{m.classifier_signal()}
								</th>
								{#each FIELDS as field (field)}
									<th
										scope="col"
										class="border-b px-3 pb-2.5 text-left text-xs font-medium text-muted-foreground"
									>
										{fieldLabel(field, null)}
									</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each table as row (row.signal)}
								<tr>
									<th
										scope="row"
										class="border-b py-3.5 pr-3 text-left font-medium whitespace-nowrap"
									>
										{NODE_LABELS[row.signal]()}
									</th>
									{#each row.cells as cell (cell.field)}
										<td class="border-b px-3 py-3.5 align-top">
											{#if cell.rate}
												<div class="flex min-w-[110px] flex-col gap-[5px]">
													<span class={cn('text-lg font-semibold', cell.best && 'text-brand')}>
														{percent(cell.rate.share)}
														{#if cell.best}
															<span
																class="ml-1.5 inline-flex h-[18px] items-center rounded-full bg-panel px-[7px] align-[2px] text-micro font-medium text-brand"
															>
																{m.classifier_signal_best()}
															</span>
														{/if}
													</span>
													<div class="h-1.5 overflow-hidden rounded-full bg-muted">
														<div
															class="h-full rounded-full bg-primary"
															style:width="{cell.rate.share * 100}%"
														></div>
													</div>
													<span class="text-xs text-muted-foreground">
														{m.classifier_signal_of({
															count: formatNumber(cell.rate.named),
															decided: formatNumber(cell.rate.decided)
														})}
													</span>
												</div>
											{:else}
												<span class="text-muted-foreground" aria-label={m.classifier_signal_none()}
													>–</span
												>
											{/if}
										</td>
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Card.Root>
	{/if}
</div>
