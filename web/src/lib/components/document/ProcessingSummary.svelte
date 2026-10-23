<script lang="ts">
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import History from '@lucide/svelte/icons/history';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import OctagonX from '@lucide/svelte/icons/octagon-x';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import type { Snippet } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import type { Changes, Headline, HeadlineTone } from '#lib/run-summary.ts';
	import { MARK } from '#lib/step-look.ts';
	import type { Counts } from '#lib/steps.ts';
	import { cn } from '#lib/utils.ts';

	// The head of the processing view (Tobi, 23.10.2026): how the run went at a glance. One
	// sentence where and why it stands, what helps next, the band of the run, how many steps
	// ended how, and what changed since the run before.
	let {
		headline,
		counts,
		changes,
		reviewHref,
		canReprocess,
		onreprocess,
		band
	}: {
		headline: Headline;
		counts: Counts;
		changes: Changes | null;
		/** The document tab with the form, for the filing question and the review. */
		reviewHref: string;
		canReprocess: boolean;
		onreprocess: () => void;
		band: Snippet;
	} = $props();

	const icons = {
		running: LoaderCircle,
		yellow: TriangleAlert,
		red: OctagonX,
		green: CircleCheck
	};
	const tiles: Record<HeadlineTone, string> = {
		running: 'bg-lane-running text-lane-running-foreground',
		yellow: 'bg-lane-yellow text-lane-yellow-foreground',
		red: 'bg-lane-red text-lane-red-foreground',
		green: 'bg-lane-green text-lane-green-foreground'
	};
	const Icon = $derived(icons[headline.tone]);

	// The counts in words, the number in bold: only what there is.
	const tallies = $derived(
		[
			{ count: counts.done, label: m.run_count_done(), dot: MARK.green },
			{ count: counts.uncertain, label: m.run_count_uncertain(), dot: MARK.yellow },
			{ count: counts.failed, label: m.run_count_failed(), dot: MARK.red },
			{
				count: counts.running,
				label: counts.running === 1 ? m.run_count_running_one() : m.run_count_running(),
				dot: 'animate-pulse bg-lane-running-foreground'
			},
			{
				count: counts.waiting,
				label: counts.waiting === 1 ? m.run_count_waiting_one() : m.run_count_waiting(),
				dot: 'border border-dashed border-muted-foreground'
			},
			{ count: counts.skipped, label: m.run_count_skipped(), dot: 'bg-muted-foreground/40' },
			{
				count: counts.carried,
				label:
					counts.carriedFrom === null
						? m.run_count_carried_earlier()
						: m.run_count_carried({ run: counts.carriedFrom }),
				dot: 'bg-muted-foreground/60'
			}
		].filter((entry) => entry.count > 0)
	);
</script>

<section
	aria-labelledby="run-headline"
	class="flex min-w-0 flex-col gap-4 rounded-2xl border bg-card p-5"
>
	<div class="flex flex-wrap items-start gap-x-3.5 gap-y-3">
		<span class={cn('grid size-10 shrink-0 place-items-center rounded-xl', tiles[headline.tone])}>
			<Icon
				class={cn('size-5', headline.tone === 'running' && 'animate-spin')}
				aria-hidden="true"
				strokeWidth={2.2}
			/>
		</span>
		<div class="flex min-w-0 flex-1 basis-60 flex-col gap-1">
			<h2 id="run-headline" class="text-lg leading-snug font-semibold">{headline.title}</h2>
			{#if headline.detail}
				<p class="text-sm leading-relaxed wrap-break-word text-muted-foreground">
					{headline.detail}
				</p>
			{/if}
		</div>
		{#if headline.action === 'filing' || headline.action === 'review'}
			<Button
				href={reviewHref}
				class="shrink-0 bg-lane-yellow-mark text-lane-yellow-on-mark ring-1 ring-lane-yellow-mark-edge ring-inset hover:bg-lane-yellow-mark/85"
			>
				{headline.action === 'filing' ? m.processing_filing_link() : m.run_to_review()}
			</Button>
		{:else if headline.action === 'reprocess' && canReprocess}
			<Button variant="outline" class="shrink-0" onclick={onreprocess}>
				<RefreshCw aria-hidden="true" />
				{m.reprocess_title()}
			</Button>
		{/if}
	</div>

	{@render band()}

	{#if tallies.length > 0 || changes}
		<div
			class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-muted pt-3 text-sm text-muted-foreground"
		>
			{#if tallies.length > 0}
				<ul class="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label={m.run_counts()}>
					{#each tallies as tally (tally.label)}
						<li class="flex items-center gap-1.5 whitespace-nowrap">
							<span class={cn('size-2 shrink-0 rounded-full', tally.dot)} aria-hidden="true"></span>
							<span
								><strong class="font-semibold text-foreground">{tally.count}</strong>
								{tally.label}</span
							>
						</li>
					{/each}
				</ul>
			{/if}
			{#if changes}
				<p class="flex min-w-0 items-start gap-1.5 sm:ml-auto">
					<History class="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
					<span class="text-foreground/85">
						{m.run_since({ run: changes.since })}
						{changes.items.join(' · ')}
					</span>
				</p>
			{/if}
		</div>
	{/if}
</section>
