<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ListChecks from '@lucide/svelte/icons/list-checks';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import type { components } from '#lib/api/schema.ts';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { describeError } from '#lib/errors.ts';
	import { fileSize } from '#lib/file-passport.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// The tab "Search index" of the page "System" (Tobi, 24.10.2026): how much of the documents
	// the index holds, with vectors, what is still to do and how long an indexing takes; admins
	// check it against the database ("Check thoroughly": it only counts). Without embeddings it
	// shows nothing of the meaning (Tobi, 24.10.2026). It asks again every ten seconds while
	// the page is in view.
	type Status = components['schemas']['SearchStatusOut'];
	type Check = components['schemas']['IndexCheckOut'];

	const POLL = 10_000;

	let status = $state<Status | null>(null);
	let problem = $state<string | null>(null);
	let missing = $state(false);
	let check = $state<Check | null>(null);
	let checking = $state(false);

	async function load() {
		try {
			status = await unwrap(api.GET('/api/v1/search/status'));
			problem = null;
		} catch (failure) {
			const code = failure instanceof ApiError ? failure.problem?.reason?.code : undefined;
			if (code === 'search_not_configured') missing = true;
			else problem = describeError(failure);
		}
	}

	onMount(() => {
		void load();
		const timer = setInterval(() => {
			if (document.visibilityState === 'visible' && !missing) void load();
		}, POLL);
		return () => clearInterval(timer);
	});

	async function runCheck() {
		if (checking) return;
		checking = true;
		try {
			check = await unwrap(api.POST('/api/v1/search/check'));
		} catch (failure) {
			toast.error(describeError(failure));
		} finally {
			checking = false;
		}
	}

	const share = (part: number, whole: number) =>
		whole === 0 ? 1 : Math.min(1, Math.max(0, part / whole));
	const percent = (value: number) =>
		formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });
	const seconds = (ms: number) => formatDuration(ms / 1000);

	const meaning = $derived(status?.model != null);
	const inIndex = $derived(status ? share(status.index.documents, status.documents) : 0);
	const embedded = $derived(status ? share(status.index.embedded, status.index.documents) : 0);
	const since = $derived(status ? formatDate(status.since, { dateStyle: 'medium' }) : '');
</script>

{#snippet bar(value: number, label: string)}
	<div
		role="progressbar"
		aria-label={label}
		aria-valuemin={0}
		aria-valuemax={100}
		aria-valuenow={Math.round(value * 100)}
		class="h-3 overflow-hidden rounded-full bg-muted"
	>
		<div class="h-full rounded-full bg-primary" style:width="{value * 100}%"></div>
	</div>
{/snippet}

{#snippet tile(value: string, label: string, mono = false)}
	<div class="flex flex-col gap-0.5 rounded-xl bg-surface px-3.5 py-3">
		<span
			class={cn(
				'font-semibold tabular-nums',
				mono ? 'pt-1 font-mono text-sm break-all' : 'text-xl'
			)}
		>
			{value}
		</span>
		<span class="text-[0.8125rem] text-muted-foreground">{label}</span>
	</div>
{/snippet}

<div class="flex flex-col gap-6">
	{#if missing}
		<p class="text-muted-foreground">{m.reason_search_not_configured()}</p>
	{:else if problem && !status}
		<LoadProblem {problem} onretry={load} />
	{:else if !status}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<div class="flex flex-wrap gap-6">
			<section
				class="flex min-w-0 flex-[2_1_520px] flex-col gap-5 rounded-2xl border bg-card px-5 py-4 sm:px-6"
			>
				<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
					<h2 class="font-semibold">{m.search_state_title()}</h2>
					{#if status.index.indexing}
						<span
							class="inline-flex h-[26px] items-center gap-2 rounded-full bg-note px-2.5 text-xs font-medium text-note-foreground"
						>
							<span
								aria-hidden="true"
								class="size-2 rounded-full bg-note-foreground ring-[3px] ring-note-foreground/20"
							></span>
							{m.search_writing()}
						</span>
					{/if}
				</div>
				<div class="flex flex-col gap-2">
					<div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
						<span>
							<span class="font-semibold">{m.search_in_index()}</span>
							<span class="text-muted-foreground">
								{m.search_in_index_of({
									indexed: formatNumber(status.index.documents),
									total: formatNumber(status.documents)
								})}
							</span>
						</span>
						<span class="text-[1.375rem] font-semibold tabular-nums">{percent(inIndex)}</span>
					</div>
					{@render bar(inIndex, m.search_in_index())}
				</div>
				{#if meaning}
					<div class="flex flex-col gap-2">
						<div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
							<span>
								<span class="font-semibold">{m.search_meaning()}</span>
								<span class="text-muted-foreground">
									{m.search_meaning_of({
										embedded: formatNumber(status.index.embedded),
										indexed: formatNumber(status.index.documents)
									})}
								</span>
							</span>
							<span class="text-[1.375rem] font-semibold tabular-nums">{percent(embedded)}</span>
						</div>
						{@render bar(embedded, m.search_meaning())}
						<span class="text-xs text-muted-foreground">{m.search_meaning_hint()}</span>
					</div>
				{/if}
				<div class="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
					{#if meaning}
						{@render tile(
							formatNumber(status.index.vectors),
							m.search_sections_label({
								average: formatNumber(
									status.index.embedded ? status.index.vectors / status.index.embedded : 0,
									{ maximumFractionDigits: 1 }
								)
							})
						)}
						{@render tile(
							status.model ?? '',
							status.dimensions
								? m.search_model_label({ dimensions: formatNumber(status.dimensions) })
								: m.search_model_label_plain(),
							true
						)}
					{/if}
					{#if status.index.size_bytes != null}
						{@render tile(fileSize(status.index.size_bytes), m.search_size_label())}
					{/if}
				</div>
			</section>

			<section
				class="flex min-w-0 flex-[1_1_280px] flex-col gap-2.5 rounded-2xl border bg-card px-5 py-4 sm:px-6"
			>
				<h2 class="font-semibold">{m.search_open_title()}</h2>
				<div class="flex items-baseline gap-2">
					<span class="text-[1.875rem] font-semibold tracking-tight tabular-nums">
						{formatNumber(status.queued + status.running)}
					</span>
					<span class="text-muted-foreground">{m.search_open_jobs()}</span>
				</div>
				<span>
					{#if status.queued + status.running === 0}
						{m.search_open_none()}
					{:else if status.remaining_ms != null}
						{m.search_open_done_in({ duration: seconds(status.remaining_ms) })}
					{:else}
						{m.search_open_unknown()}
					{/if}
				</span>
				<span class="text-[0.8125rem] text-muted-foreground">{m.search_open_hint()}</span>
				<div aria-hidden="true" class="my-1.5 h-px bg-border"></div>
				<span class="text-[0.8125rem] text-muted-foreground">
					{m.search_open_split({
						running: formatNumber(status.running),
						queued: formatNumber(status.queued)
					})}
				</span>
				<a
					href="?tab=jobs"
					class="inline-flex items-center gap-1.5 text-[0.8125rem] text-primary hover:underline"
				>
					{m.search_open_link()}<ArrowRight class="size-3.5" aria-hidden="true" />
				</a>
			</section>
		</div>

		<section class="rounded-2xl border bg-card px-5 py-4 sm:px-6">
			<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
				<h2 class="font-semibold">{m.search_durations_title()}</h2>
				<span class="text-[0.8125rem] text-muted-foreground">
					{m.search_durations_since({ date: since })}
				</span>
			</div>
			{#if !status.embedded_jobs && !status.plain_jobs}
				<p class="mt-3 text-muted-foreground">{m.search_durations_none({ date: since })}</p>
			{:else}
				<div class="mt-4 grid grid-cols-[repeat(auto-fit,minmax(min(280px,100%),1fr))] gap-4">
					{#each [[m.search_with_embedding(), status.embedded_jobs, true], [m.search_without_embedding(), status.plain_jobs, false]] as const as [label, times, embedding] (label)}
						{#if times && (meaning || !embedding)}
							<div class="flex flex-col gap-1 rounded-xl border p-4">
								<span class="text-[0.8125rem] text-muted-foreground">{label}</span>
								<div class="flex items-baseline gap-2">
									<span class="text-[1.75rem] font-semibold tracking-tight tabular-nums">
										{seconds(times.median_ms)}
									</span>
									<span class="text-[0.8125rem] text-muted-foreground">{m.search_median()}</span>
								</div>
								<span class="text-[0.8125rem] text-muted-foreground">
									{m.search_jobs_line({
										p90: seconds(times.p90_ms),
										count: formatNumber(times.count)
									})}
									{#if embedding && status.per_section_ms != null}
										· {m.search_per_section({ duration: seconds(status.per_section_ms) })}
									{/if}
								</span>
							</div>
						{/if}
					{/each}
				</div>
				{#if meaning}
					<p class="mt-3.5 max-w-3xl text-[0.8125rem] text-muted-foreground">
						{m.search_durations_note()}
					</p>
				{/if}
			{/if}
		</section>

		{#if session.isAdmin}
			<section class="flex flex-col gap-4 rounded-2xl border bg-card px-5 py-4 sm:px-6">
				<div class="flex flex-wrap items-start justify-between gap-3">
					<div class="flex max-w-2xl flex-col gap-1">
						<h2 class="font-semibold">{m.search_check_title()}</h2>
						<span class="text-[0.8125rem] text-muted-foreground">{m.search_check_text()}</span>
					</div>
					<Button variant="outline" disabled={checking} onclick={runCheck}>
						<ListChecks aria-hidden="true" />{m.search_check_button()}
					</Button>
				</div>
				{#if check}
					<span class="text-[0.8125rem] text-muted-foreground">
						{m.search_check_took({ duration: seconds(check.took_ms) })}
					</span>
					<div class="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
						{#each [[check.current, m.search_check_current(), 'good'], [check.missing, m.search_check_missing(), 'bad'], [check.outdated, m.search_check_outdated(), 'bad'], [check.other_model, m.search_check_other_model(), 'bad'], [check.extra, m.search_check_extra(), 'bad']] as const as [count, label, kind] (label)}
							{#if kind === 'good' || count > 0 || label === m.search_check_missing()}
								<div
									class={cn(
										'flex flex-col gap-1 rounded-xl px-4 py-3.5',
										kind === 'good'
											? 'bg-lane-green text-lane-green-foreground ring-1 ring-lane-green-foreground/35 ring-inset'
											: count > 0
												? 'bg-lane-yellow text-lane-yellow-foreground ring-1 ring-lane-yellow-foreground/35 ring-inset'
												: 'bg-surface'
									)}
								>
									<span class="text-[1.375rem] font-semibold tabular-nums"
										>{formatNumber(count)}</span
									>
									<span class="text-[0.8125rem]">{label}</span>
								</div>
							{/if}
						{/each}
					</div>
				{/if}
			</section>
		{/if}
	{/if}
</div>
