<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { documentHref } from '#lib/candidates.ts';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import {
		countOf,
		jobTiming,
		kindLabel,
		OPEN_STATES,
		STATE_LABELS,
		totals,
		workersStill,
		type Job,
		type JobState,
		type JobsSummary,
		type KindDurations
	} from '#lib/jobs.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { PagedList } from '#lib/paging.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// The tab "Jobs" of the page "System" (Tobi, 24.10.2026): whether a worker takes jobs, how
	// many stand where, the open jobs by kind (opened one kind at a time), the failed ones
	// (admins try them again) and how long the done ones waited and ran. It asks again every
	// five seconds while the page is in view, the durations every minute; no events.
	type View = 'open' | 'failed' | 'done';
	type Durations = components['schemas']['JobDurationsOut'];

	const POLL = 5_000;
	const SLOW_POLL = 60_000;
	const PAGE = 20;

	let view = $state<View>('open');
	let kind = $state('');
	let summary = $state<JobsSummary | null>(null);
	let durations = $state<Durations | null>(null);
	let problem = $state<string | null>(null);
	let groups = $state<Record<string, PagedList<Job>>>({});
	let busy = $state<string | null>(null);

	const failed = new PagedList<Job>((after) => page(['failed'], kind || null, after));

	async function page(
		states: readonly JobState[],
		of: string | null,
		after: string | number | null
	) {
		const offset = typeof after === 'number' ? after : 0;
		const found = await unwrap(
			api.GET('/api/v1/jobs', {
				params: { query: { state: [...states], kind: of ?? undefined, offset, limit: PAGE } }
			})
		);
		return { items: found.items, next: found.next_offset ?? null, total: found.total };
	}

	async function loadSummary() {
		try {
			summary = await unwrap(api.GET('/api/v1/jobs/summary'));
			problem = null;
		} catch (failure) {
			problem = describeError(failure);
		}
	}

	async function loadDurations() {
		try {
			durations = await unwrap(api.GET('/api/v1/jobs/durations'));
		} catch {
			// The counts still show; the next minute tries again.
		}
	}

	async function refresh() {
		await loadSummary();
		for (const list of Object.values(groups)) void list.refresh();
		if (view === 'failed') void failed.refresh();
	}

	onMount(() => {
		void loadSummary();
		void loadDurations();
		const visible = () => document.visibilityState === 'visible';
		const fast = setInterval(() => visible() && void refresh(), POLL);
		const slow = setInterval(() => visible() && void loadDurations(), SLOW_POLL);
		return () => {
			clearInterval(fast);
			clearInterval(slow);
		};
	});

	function toggle(of: string) {
		if (groups[of]) {
			delete groups[of];
			return;
		}
		const list = new PagedList<Job>((after) => page(OPEN_STATES, of, after));
		groups[of] = list;
		void list.reload();
	}

	function show(next: string) {
		view = next as View;
		if (view === 'failed') void failed.reload();
	}

	function choose(next: string) {
		kind = next;
		groups = {};
		if (kind && open.some((item) => item.kind === kind)) toggle(kind);
		if (view === 'failed') void failed.reload();
	}

	async function retry(job: Job) {
		if (busy) return;
		busy = job.id;
		try {
			if (job.retry === 'document' && job.document) {
				await unwrap(
					api.POST('/api/v1/documents/{id}/retry', { params: { path: { id: job.document.id } } })
				);
				toast.success(m.jobs_retry_document());
			} else {
				await unwrap(api.POST('/api/v1/jobs/{id}/retry', { params: { path: { id: job.id } } }));
				toast.success(m.jobs_retry_queued());
			}
			await refresh();
			void failed.refresh();
		} catch (failure) {
			toast.error(describeError(failure));
		} finally {
			busy = null;
		}
	}

	const now = $derived(summary ? new Date(summary.now) : new Date());
	const all = $derived(summary ? totals(summary.kinds) : null);
	const open = $derived(
		(summary?.kinds ?? []).filter(
			(item) => countOf(item, OPEN_STATES) > 0 && (!kind || item.kind === kind)
		)
	);
	const timesOf = $derived(
		new Map((durations?.kinds ?? []).map((item) => [item.kind, item] as const))
	);
	const done = $derived((durations?.kinds ?? []).filter((item) => !kind || item.kind === kind));
	const keptSince = $derived(
		summary ? formatDate(summary.kept_since, { dateStyle: 'medium' }) : ''
	);
	const still = $derived(summary ? workersStill(summary) : false);
	const lastStarted = $derived(
		summary?.last_started_at
			? m.jobs_worker_last({
					ago: formatDuration((now.getTime() - new Date(summary.last_started_at).getTime()) / 1000)
				})
			: m.jobs_worker_never()
	);
	const kindOptions = $derived([
		{ value: '', label: m.jobs_kind_all() },
		...(summary?.kinds ?? [])
			.map((item) => ({ value: item.kind, label: kindLabel(item.kind) }))
			.sort((a, b) => a.label.localeCompare(b.label))
	]);

	const CHIP =
		'inline-flex h-[22px] items-center rounded-full px-2 text-xs font-medium whitespace-nowrap';
	const TONES: Record<JobState, string> = {
		running: 'bg-primary/10 text-primary ring-1 ring-primary/30 ring-inset',
		due: 'bg-muted text-muted-foreground',
		planned: 'bg-note text-note-foreground ring-1 ring-note-foreground/30 ring-inset',
		failed: 'bg-lane-red text-lane-red-foreground ring-1 ring-lane-red-foreground/35 ring-inset',
		done: 'bg-lane-green text-lane-green-foreground ring-1 ring-lane-green-foreground/35 ring-inset'
	};

	function groupTimes(times: KindDurations | undefined): string | null {
		if (!times) return null;
		return m.jobs_group_times({
			wait: formatDuration(times.wait_median_ms / 1000),
			run: formatDuration(times.run_median_ms / 1000)
		});
	}
</script>

{#snippet row(job: Job, withKind: boolean)}
	<li class="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t py-2.5">
		<span class={cn(CHIP, TONES[job.state])}>{STATE_LABELS[job.state]()}</span>
		{#if job.node}
			<span class="font-medium">{NODE_LABELS[job.node]()}</span>
		{:else if withKind}
			<span class="font-medium">{kindLabel(job.kind)}</span>
		{/if}
		{#if job.document}
			<a href={documentHref(job.document.id)} class="min-w-0 text-primary hover:underline">
				{job.document.title}
			</a>
		{:else if job.document_hidden}
			<span class="text-muted-foreground italic">{m.jobs_hidden_document()}</span>
		{/if}
		{#if job.contact}<span>{job.contact}</span>{/if}
		<span class="ml-auto text-[0.8125rem] text-muted-foreground tabular-nums">
			{jobTiming(job, now)}
		</span>
		{#if job.retry}
			<Button size="sm" variant="outline" disabled={busy !== null} onclick={() => retry(job)}>
				<RotateCw aria-hidden="true" />{m.jobs_retry()}
			</Button>
		{/if}
		{#if job.error}
			<p class="basis-full text-xs text-lane-red-foreground">
				{m.jobs_last_error()} <span class="font-mono">{job.error}</span>
			</p>
		{/if}
	</li>
{/snippet}

{#snippet more(list: PagedList<Job>)}
	{#if list.hasMore}
		<Button variant="ghost" size="sm" disabled={list.loading} onclick={() => list.more()}>
			{m.load_more()}
		</Button>
	{/if}
{/snippet}

<div class="flex flex-col gap-6">
	{#if problem && !summary}
		<LoadProblem {problem} onretry={loadSummary} />
	{:else if !summary || !all}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
			<p class="flex items-center gap-2.5">
				<span
					aria-hidden="true"
					class={cn(
						'size-2.5 rounded-full',
						still
							? 'bg-lane-yellow-foreground ring-4 ring-lane-yellow'
							: 'bg-lane-green-foreground ring-4 ring-lane-green'
					)}
				></span>
				<span>
					<span class="font-medium">{still ? m.jobs_worker_stale() : m.jobs_worker_active()}</span>
					<span class="text-muted-foreground">· {lastStarted}</span>
				</span>
			</p>
			<span class="text-[0.8125rem] text-muted-foreground">{m.jobs_refreshing()}</span>
		</div>

		<div class="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
			{#each [['running', m.jobs_hint_running()], ['due', m.jobs_hint_due()], ['planned', m.jobs_hint_planned()], ['failed', m.jobs_hint_kept( { date: keptSince } )], ['done', m.jobs_hint_kept( { date: keptSince } )]] as const as [state, hint] (state)}
				<div
					class={cn(
						'flex flex-col gap-0.5 rounded-2xl border bg-card px-4 py-3.5',
						state === 'failed' &&
							all.failed > 0 &&
							'border-lane-red-foreground/35 bg-lane-red text-lane-red-foreground',
						state === 'done' && 'bg-surface'
					)}
				>
					<span class="text-[1.625rem] font-semibold tracking-tight tabular-nums">
						{formatNumber(all[state])}
					</span>
					<span class="text-[0.8125rem] font-medium">{STATE_LABELS[state]()}</span>
					<span class="text-xs text-muted-foreground">{hint}</span>
				</div>
			{/each}
		</div>

		<div class="flex flex-wrap items-center justify-between gap-3">
			<Segmented
				label={m.jobs_view()}
				value={view}
				onchange={show}
				options={[
					{
						value: 'open',
						label: m.jobs_view_open(),
						count: formatNumber(all.running + all.due + all.planned)
					},
					{ value: 'failed', label: m.jobs_view_failed(), count: formatNumber(all.failed) },
					{ value: 'done', label: m.jobs_view_done() }
				]}
			/>
			<Select
				aria-label={m.jobs_kind()}
				class="w-auto min-w-48"
				value={kind}
				onchange={choose}
				options={kindOptions}
			/>
		</div>

		{#if view === 'open'}
			<section class="rounded-2xl border bg-card px-5 py-1 sm:px-6">
				<h2 class="sr-only">{m.jobs_open_title()}</h2>
				{#each open as item, index (item.kind)}
					{@const list = groups[item.kind]}
					<div class={cn(index > 0 && 'border-t')}>
						<button
							type="button"
							aria-expanded={list !== undefined}
							onclick={() => toggle(item.kind)}
							class="flex w-full flex-wrap items-center gap-x-3 gap-y-2 py-3.5 text-left"
						>
							<ChevronRight
								aria-hidden="true"
								class={cn(
									'size-4 shrink-0 text-muted-foreground transition-transform',
									list && 'rotate-90'
								)}
							/>
							<span class="font-semibold">{kindLabel(item.kind)}</span>
							{#each OPEN_STATES as state (state)}
								{#if item[state] > 0}
									<span class={cn(CHIP, TONES[state])}>
										{STATE_LABELS[state]()}
										{formatNumber(item[state])}
									</span>
								{/if}
							{/each}
							{#if groupTimes(timesOf.get(item.kind))}
								<span class="ml-auto text-[0.8125rem] text-muted-foreground">
									{groupTimes(timesOf.get(item.kind))}
								</span>
							{/if}
						</button>
						{#if list}
							<ul class="mb-3 pl-7">
								{#each list.items as job (job.id)}
									{@render row(job, false)}
								{/each}
							</ul>
							<div class="mb-3 pl-7">{@render more(list)}</div>
						{/if}
					</div>
				{:else}
					<p class="py-4 text-muted-foreground">{m.jobs_none_open()}</p>
				{/each}
			</section>
		{:else if view === 'failed'}
			<section class="rounded-2xl border bg-card px-5 py-4 sm:px-6">
				<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
					<h2 class="font-semibold">{m.jobs_failed_title()}</h2>
					<span class="text-[0.8125rem] text-muted-foreground">
						{m.jobs_kept_since({ date: keptSince })}
					</span>
				</div>
				{#if failed.empty}
					<p class="mt-3 text-muted-foreground">{m.jobs_none_failed({ date: keptSince })}</p>
				{:else}
					<ul class="mt-3">
						{#each failed.items as job (job.id)}
							{@render row(job, true)}
						{/each}
					</ul>
					{@render more(failed)}
				{/if}
			</section>
		{:else}
			<section class="rounded-2xl border bg-card px-5 py-4 sm:px-6">
				<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
					<h2 class="font-semibold">{m.jobs_done_title({ date: keptSince })}</h2>
					<span class="text-[0.8125rem] text-muted-foreground">{m.jobs_done_note()}</span>
				</div>
				{#if done.length === 0}
					<p class="mt-3 text-muted-foreground">{m.jobs_none_done({ date: keptSince })}</p>
				{:else}
					<div class="mt-3 overflow-x-auto">
						<table class="w-full min-w-[560px] border-collapse text-[0.8125rem] tabular-nums">
							<thead>
								<tr class="border-b text-xs text-muted-foreground">
									<th scope="col" class="py-2 pr-3 text-left font-medium">{m.jobs_col_kind()}</th>
									<th scope="col" class="px-3 py-2 text-right font-medium">{m.jobs_col_count()}</th>
									<th scope="col" class="px-3 py-2 text-right font-medium">{m.jobs_col_wait()}</th>
									<th scope="col" class="px-3 py-2 text-right font-medium">{m.jobs_col_run()}</th>
									<th scope="col" class="py-2 pl-3 text-right font-medium"
										>{m.jobs_col_run_p90()}</th
									>
								</tr>
							</thead>
							<tbody>
								{#each done as item (item.kind)}
									<tr class="border-b last:border-b-0">
										<th scope="row" class="py-2.5 pr-3 text-left font-medium whitespace-nowrap">
											{kindLabel(item.kind)}
										</th>
										<td class="px-3 py-2.5 text-right">{formatNumber(item.count)}</td>
										<td class="px-3 py-2.5 text-right text-muted-foreground">
											{formatDuration(item.wait_median_ms / 1000)}
										</td>
										<td class="px-3 py-2.5 text-right"
											>{formatDuration(item.run_median_ms / 1000)}</td
										>
										<td class="py-2.5 pl-3 text-right text-muted-foreground">
											{formatDuration(item.run_p90_ms / 1000)}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</section>
		{/if}
	{/if}
</div>
