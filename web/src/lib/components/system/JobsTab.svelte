<script lang="ts">
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { documentHref } from '#lib/candidates.ts';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import {
		jobDue,
		jobRun,
		jobWait,
		kindLabel,
		OPEN_STATES,
		STATE_LABELS,
		totals,
		workersStill,
		type Job,
		type JobState,
		type JobsSummary
	} from '#lib/jobs.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { Pager } from '#lib/paging.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import { cardVariants } from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import type { Tone } from '#lib/tones.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import Loading from '#lib/components/Loading.svelte';

	// The tab "Jobs" of the page "System" (Tobi, 24.10.2026; a table with pages since
	// 26.10.2026): whether a worker takes jobs, how many stand where, and the jobs as a table,
	// the open ones in the order the workers take them (what runs next on top), the failed ones
	// (admins try them again) and the done ones with how long each waited and ran, by state and
	// kind; below the done ones, how long each kind takes. It asks again every five seconds
	// while the page is in view, the durations every minute; no events.
	type View = 'open' | 'failed' | 'done';
	type Durations = components['schemas']['JobDurationsOut'];

	const POLL = 5_000;
	const SLOW_POLL = 60_000;
	const PAGE = 50;
	const STATES: Record<View, readonly JobState[]> = {
		open: OPEN_STATES,
		failed: ['failed'],
		done: ['done']
	};

	let view = $state<View>('open');
	let kind = $state('');
	let summary = $state<JobsSummary | null>(null);
	let durations = $state<Durations | null>(null);
	let problem = $state<string | null>(null);
	let busy = $state<string | null>(null);

	const jobs = new Pager<Job>(async (offset, limit) => {
		const found = await unwrap(
			api.GET('/api/v1/jobs', {
				params: {
					query: { state: [...STATES[view]], kind: kind || undefined, offset, limit }
				}
			})
		);
		return { items: found.items, total: found.total };
	}, PAGE);

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
		void jobs.refresh();
	}

	onMount(() => {
		void loadSummary();
		void loadDurations();
		void jobs.reload();
		const visible = () => document.visibilityState === 'visible';
		const fast = setInterval(() => visible() && void refresh(), POLL);
		const slow = setInterval(() => visible() && void loadDurations(), SLOW_POLL);
		return () => {
			clearInterval(fast);
			clearInterval(slow);
		};
	});

	function show(next: string) {
		view = next as View;
		void jobs.reload();
	}

	function choose(next: string) {
		kind = next;
		void jobs.reload();
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
		} catch (failure) {
			toast.error(describeError(failure));
		} finally {
			busy = null;
		}
	}

	const now = $derived(summary ? new Date(summary.now) : new Date());
	const all = $derived(summary ? totals(summary.kinds) : null);
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
	const anyRetry = $derived(jobs.items.some((job) => job.retry));
	const title = $derived(
		view === 'open'
			? m.jobs_open_title()
			: view === 'failed'
				? m.jobs_failed_title()
				: m.jobs_done_title({ date: keptSince })
	);
	const info = $derived(
		view === 'open'
			? m.jobs_open_info()
			: view === 'failed'
				? m.jobs_failed_info()
				: m.jobs_done_info()
	);
	const dueColumn = $derived(
		view === 'open'
			? m.jobs_col_due()
			: view === 'failed'
				? m.jobs_col_failed_at()
				: m.jobs_col_finished()
	);
	const none = $derived(
		view === 'open'
			? m.jobs_none_open()
			: view === 'failed'
				? m.jobs_none_failed({ date: keptSince })
				: m.jobs_none_done({ date: keptSince })
	);

	const TONES: Record<JobState, Tone> = {
		running: 'primary',
		due: 'muted',
		planned: 'note',
		failed: 'red',
		done: 'green'
	};
	const NUMBER = 'text-right tabular-nums';
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
	{#if problem && !summary}
		<LoadProblem {problem} onretry={loadSummary} />
	{:else if !summary || !all}
		<Loading />
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
			<span class="text-meta text-muted-foreground">{m.jobs_refreshing()}</span>
		</div>

		<div class="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
			{#each [['running', m.jobs_hint_running()], ['due', m.jobs_hint_due()], ['planned', m.jobs_hint_planned()], ['failed', m.jobs_hint_kept( { date: keptSince } )], ['done', m.jobs_hint_kept( { date: keptSince } )]] as const as [state, hint] (state)}
				<div
					class={cn(
						cardVariants({ size: 'flush' }),
						'flex flex-col gap-0.5 px-4 py-3.5',
						state === 'failed' &&
							all.failed > 0 &&
							'border-lane-red-foreground/35 bg-lane-red text-lane-red-foreground',
						state === 'done' && 'bg-surface'
					)}
				>
					<span class="text-figure tabular-nums">
						{formatNumber(all[state])}
					</span>
					<span class="text-meta font-medium">{STATE_LABELS[state]()}</span>
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
					{ value: 'done', label: m.jobs_view_done(), count: formatNumber(all.done) }
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

		<Card.Root as="section" size="lg">
			<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
				{@render heading(title, info)}
				{#if view === 'open'}
					<span class="text-meta text-muted-foreground">{m.jobs_order_note()}</span>
				{:else}
					<span class="text-meta text-muted-foreground">
						{m.jobs_kept_since({ date: keptSince })}
					</span>
				{/if}
			</div>
			{#if jobs.error && !jobs.loaded}
				<div class="mt-3">
					<LoadProblem problem={describeError(jobs.error)} onretry={() => jobs.reload()} />
				</div>
			{:else if jobs.empty}
				<p class="mt-3 text-muted-foreground">{none}</p>
			{:else if jobs.items.length}
				<div class="mt-3">
					<Table.Root class="min-w-[760px] text-meta">
						<Table.Header>
							<Table.Row class="text-xs text-muted-foreground">
								<Table.Head class="pl-0">{m.jobs_col_kind()}</Table.Head>
								<Table.Head>{m.jobs_col_status()}</Table.Head>
								<Table.Head>{m.jobs_col_document()}</Table.Head>
								<Table.Head>{dueColumn}</Table.Head>
								<Table.Head class={NUMBER}>{m.jobs_col_attempts()}</Table.Head>
								<Table.Head class={NUMBER}>{m.jobs_col_wait_time()}</Table.Head>
								<Table.Head class={cn(NUMBER, !anyRetry && 'pr-0')}
									>{m.jobs_col_run_time()}</Table.Head
								>
								{#if anyRetry}
									<Table.Head class="pr-0"
										><span class="sr-only">{m.jobs_col_actions()}</span></Table.Head
									>
								{/if}
							</Table.Row>
						</Table.Header>
						<Table.Body>
							{#each jobs.items as job (job.id)}
								<Table.Row class={cn(job.error && 'border-b-0')}>
									<Table.Cell class="pl-0 font-medium">
										{job.node ? NODE_LABELS[job.node]() : kindLabel(job.kind)}
									</Table.Cell>
									<Table.Cell>
										<Badge variant={TONES[job.state]}>{STATE_LABELS[job.state]()}</Badge>
									</Table.Cell>
									<Table.Cell class="max-w-[22rem] truncate">
										{#if job.document}
											<a href={documentHref(job.document.id)} class="text-brand hover:underline">
												{job.document.title}
											</a>
										{:else if job.document_hidden}
											<span class="text-muted-foreground italic">{m.jobs_hidden_document()}</span>
										{:else if job.contact}
											{job.contact}
										{:else}
											<span class="text-muted-foreground">–</span>
										{/if}
									</Table.Cell>
									<Table.Cell class="text-muted-foreground tabular-nums"
										>{jobDue(job, now)}</Table.Cell
									>
									<Table.Cell class={NUMBER}>{formatNumber(job.attempts)}</Table.Cell>
									<Table.Cell class={cn(NUMBER, 'text-muted-foreground')}
										>{jobWait(job, now)}</Table.Cell
									>
									<Table.Cell class={cn(NUMBER, !anyRetry && 'pr-0')}>{jobRun(job, now)}</Table.Cell
									>
									{#if anyRetry}
										<Table.Cell class="w-px py-1 pr-0 text-right">
											{#if job.retry}
												<Button
													size="sm"
													variant="outline"
													disabled={busy !== null}
													onclick={() => retry(job)}
												>
													<RotateCw aria-hidden="true" />{m.jobs_retry()}
												</Button>
											{/if}
										</Table.Cell>
									{/if}
								</Table.Row>
								{#if job.error}
									<Table.Row>
										<Table.Cell
											colspan={anyRetry ? 8 : 7}
											class="pt-0 pl-0 text-xs whitespace-normal text-lane-red-foreground"
										>
											{m.jobs_last_error()} <span class="font-mono">{job.error}</span>
										</Table.Cell>
									</Table.Row>
								{/if}
							{/each}
						</Table.Body>
					</Table.Root>
				</div>
				<div class="mt-4">
					<Pagination
						page={jobs.page}
						total={jobs.total}
						size={PAGE}
						onchange={(page) => jobs.go(page)}
					/>
				</div>
			{:else}
				<Loading class="mt-3" />
			{/if}
		</Card.Root>

		{#if view === 'done'}
			<Card.Root as="section" size="lg">
				<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
					{@render heading(m.jobs_durations_title(), m.jobs_durations_info())}
					<span class="text-meta text-muted-foreground">
						{m.jobs_kept_since({ date: keptSince })}
					</span>
				</div>
				{#if done.length === 0}
					<p class="mt-3 text-muted-foreground">{m.jobs_none_done({ date: keptSince })}</p>
				{:else}
					<div class="mt-3">
						<Table.Root class="min-w-[560px] text-meta">
							<Table.Header>
								<Table.Row class="text-xs text-muted-foreground">
									<Table.Head class="pl-0">{m.jobs_col_kind()}</Table.Head>
									<Table.Head class={NUMBER}>{m.jobs_col_count()}</Table.Head>
									<Table.Head class={NUMBER}>{m.jobs_col_wait()}</Table.Head>
									<Table.Head class={NUMBER}>{m.jobs_col_run()}</Table.Head>
									<Table.Head class={cn(NUMBER, 'pr-0')}>{m.jobs_col_run_p90()}</Table.Head>
								</Table.Row>
							</Table.Header>
							<Table.Body>
								{#each done as item (item.kind)}
									<Table.Row>
										<Table.Cell class="pl-0 font-medium">{kindLabel(item.kind)}</Table.Cell>
										<Table.Cell class={NUMBER}>{formatNumber(item.count)}</Table.Cell>
										<Table.Cell class={cn(NUMBER, 'text-muted-foreground')}>
											{formatDuration(item.wait_median_ms / 1000)}
										</Table.Cell>
										<Table.Cell class={NUMBER}
											>{formatDuration(item.run_median_ms / 1000)}</Table.Cell
										>
										<Table.Cell class={cn(NUMBER, 'pr-0 text-muted-foreground')}>
											{formatDuration(item.run_p90_ms / 1000)}
										</Table.Cell>
									</Table.Row>
								{/each}
							</Table.Body>
						</Table.Root>
					</div>
				{/if}
			</Card.Root>
		{/if}
	{/if}
</div>
