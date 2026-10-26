<script lang="ts">
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import type { components } from '#lib/api/schema.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { glanceSeconds, type Glance } from '#lib/runs.ts';
	import { cn } from '#lib/utils.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';

	type Status = components['schemas']['ProcessingStatus'];

	// The runs of a document, as the box of the log before (Tobi, 23.10.2026): the list to
	// choose one from (where there is more than one), how the chosen one stands or ended, when
	// it began, how long it took, the language model's tokens in it; and "Neu verarbeiten".
	let {
		runs,
		shown,
		glanceOf,
		tokens,
		canReprocess,
		onchoose,
		onreprocess
	}: {
		/** The latest first. */
		runs: readonly number[];
		shown: number;
		glanceOf: (run: number) => Glance;
		tokens: { input: number; output: number } | null;
		canReprocess: boolean;
		onchoose: (run: number) => void;
		onreprocess: () => void;
	} = $props();

	const statusLabel: Record<Status, () => string> = {
		processing: m.lane_running,
		review: m.lane_yellow,
		failed: m.outcome_failed,
		completed: m.lane_green
	};
	const statusText: Record<Status, string> = {
		processing: 'text-lane-running-foreground',
		review: 'text-lane-yellow-foreground',
		failed: 'text-lane-red-foreground',
		completed: 'text-lane-green-foreground'
	};

	const current = $derived(glanceOf(shown));
	const length = (value: Glance) => {
		const seconds = glanceSeconds(value);
		return seconds === null ? null : formatDuration(seconds);
	};
</script>

<Card.Root as="section" aria-labelledby="runs-heading" class="flex min-w-0 flex-col gap-4">
	{#if runs.length > 1}
		<SectionTitle size="card" id="runs-heading">{m.log_runs()}</SectionTitle>
		<ul class="-mx-2 -mt-2 flex max-h-80 flex-col gap-0.5 overflow-y-auto">
			{#each runs as run (run)}
				{@const glance = run === shown ? current : glanceOf(run)}
				{@const took = length(glance)}
				<li>
					<button
						type="button"
						aria-pressed={run === shown}
						onclick={() => onchoose(run)}
						class={cn(
							'flex min-h-11 w-full flex-col justify-center rounded-lg px-2 py-1.5 text-left text-sm transition-colors',
							run === shown ? 'bg-secondary' : 'hover:bg-secondary/60'
						)}
					>
						<span class="flex flex-wrap items-baseline gap-x-2">
							<span class="font-medium">{m.log_run({ run })}</span>
							<span class={statusText[glance.status]}>{statusLabel[glance.status]()}</span>
						</span>
						{#if glance.started}
							<span class="whitespace-nowrap text-muted-foreground tabular-nums">
								{[formatDate(glance.started, { dateStyle: 'short', timeStyle: 'short' }), took]
									.filter(Boolean)
									.join(' · ')}
							</span>
						{/if}
					</button>
				</li>
			{/each}
		</ul>
	{:else}
		<SectionTitle size="card" id="runs-heading">{m.log_run({ run: shown })}</SectionTitle>
	{/if}
	<dl
		class={cn(
			'grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm',
			runs.length > 1 && 'border-t border-muted pt-4'
		)}
	>
		<dt class="text-muted-foreground">{m.log_status()}</dt>
		<dd>{statusLabel[current.status]()}</dd>
		{#if current.started}
			<dt class="text-muted-foreground">{m.log_started()}</dt>
			<dd class="tabular-nums">
				{formatDate(current.started, { dateStyle: 'medium', timeStyle: 'medium' })}
			</dd>
		{/if}
		{#if length(current)}
			<dt class="text-muted-foreground">{m.log_duration()}</dt>
			<dd class="whitespace-nowrap tabular-nums">{length(current)}</dd>
		{/if}
		{#if tokens}
			<dt class="text-muted-foreground">{m.log_tokens()}</dt>
			<dd class="tabular-nums">
				{m.log_tokens_sum({
					input: formatNumber(tokens.input),
					output: formatNumber(tokens.output)
				})}
			</dd>
		{/if}
	</dl>
	{#if canReprocess}
		<div class="border-t border-muted pt-4">
			<Button variant="outline" onclick={onreprocess}>
				<RefreshCw aria-hidden="true" />
				{m.reprocess_title()}
			</Button>
		</div>
	{/if}
</Card.Root>
