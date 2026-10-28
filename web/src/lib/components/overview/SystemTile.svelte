<script lang="ts">
	import Activity from '@lucide/svelte/icons/activity';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import OctagonX from '@lucide/svelte/icons/octagon-x';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { onMount } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { BASE } from '#lib/base.ts';
	import Figure from '#lib/components/overview/Figure.svelte';
	import Tile from '#lib/components/overview/Tile.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Skeleton } from '#lib/components/ui/skeleton/index.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { type JobsSummary, kindLabel, totals, workersStill } from '#lib/jobs.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The jobs on the overview: the failed ones by kind (admins try them again on the page
	// "System"), whether a worker takes jobs, and how many are due. Asked again every 30 seconds
	// while the page is in view.
	const POLL = 30_000;

	let summary = $state<JobsSummary | null>(null);
	let problem = $state<string | null>(null);

	async function load() {
		try {
			summary = await unwrap(api.GET('/api/v1/jobs/summary'));
			problem = null;
		} catch (error) {
			problem = describeError(error);
		}
	}

	onMount(() => {
		void load();
		const timer = setInterval(() => document.visibilityState === 'visible' && void load(), POLL);
		return () => clearInterval(timer);
	});

	const all = $derived(summary ? totals(summary.kinds) : null);
	const failed = $derived((summary?.kinds ?? []).filter((kind) => kind.failed > 0));
	const still = $derived(summary ? workersStill(summary) : false);
	// The line under the badges: when a worker last started a job; "active" before it unless
	// the badge already says that none takes jobs.
	const worker = $derived.by(() => {
		if (!summary) return '';
		if (!summary.last_started_at) return m.jobs_worker_never();
		const ago =
			(new Date(summary.now).getTime() - new Date(summary.last_started_at).getTime()) / 1000;
		const last = m.jobs_worker_last({ ago: formatDuration(Math.max(0, ago)) });
		return still ? last : `${m.jobs_worker_active()} · ${last}`;
	});
</script>

<Tile
	title={m.nav_system()}
	icon={Activity}
	href={`${BASE}/system?tab=jobs`}
	go={m.overview_jobs_go()}
>
	{#if problem}
		<LoadProblem {problem} onretry={load} />
	{:else if !summary || !all}
		<Skeleton class="h-9 w-24" />
	{:else}
		{#if all.failed > 0}
			<Figure count={all.failed} label={m.overview_jobs_failed()} />
			<ul class="flex flex-wrap gap-1.5">
				{#each failed as kind (kind.kind)}
					<li>
						<Badge variant="red"
							><OctagonX aria-hidden="true" />{m.overview_failed_kind({
								kind: kindLabel(kind.kind),
								count: formatNumber(kind.failed)
							})}</Badge
						>
					</li>
				{/each}
			</ul>
		{:else if still}
			<p>
				<Badge variant="yellow" size="md"
					><TriangleAlert aria-hidden="true" />{m.jobs_worker_stale()}</Badge
				>
			</p>
		{:else}
			<p>
				<Badge variant="green" size="md"
					><CircleCheck aria-hidden="true" />{m.overview_jobs_ok()}</Badge
				>
			</p>
		{/if}
		<p class="text-meta text-muted-foreground">
			{worker}
			{#if all.due > 0}· {m.overview_jobs_due({ count: formatNumber(all.due) })}{/if}
		</p>
	{/if}
</Tile>
