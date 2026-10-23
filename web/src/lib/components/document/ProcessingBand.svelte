<script lang="ts">
	import type { BandPhase, BandStep, BandTone } from '#lib/band.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { PHASE_LABELS, type Phase } from '#lib/steps.ts';
	import { cn } from '#lib/utils.ts';

	// The run in one bar (`band`): the phases side by side by how long they took, the steps by
	// their duration and colour, the steps that ran beside the longest one as thin stripes below
	// it. Wide, the phases' names stand below their part of the bar; narrow, in one line.
	let {
		phases,
		run,
		wide,
		phaseDuration,
		carriedLabel
	}: {
		phases: readonly BandPhase[];
		run: number;
		wide: boolean;
		phaseDuration: (phase: Phase) => string | null;
		/** Where the steps of a phase the run kept come from ("aus Lauf 1"). */
		carriedLabel: string;
	} = $props();

	const tones: Record<BandTone, string> = {
		green: 'bg-lane-green-foreground/80',
		yellow: 'bg-lane-yellow-foreground',
		red: 'bg-lane-red-foreground',
		running: 'animate-pulse bg-lane-running-foreground/50',
		waiting:
			'border border-dashed border-muted-foreground/60 bg-[repeating-linear-gradient(45deg,var(--color-muted)_0_4px,transparent_4px_8px)]'
	};
	const words: Record<BandTone, () => string> = {
		green: m.outcome_ok,
		yellow: m.outcome_uncertain,
		red: m.outcome_failed,
		running: m.node_status_running,
		waiting: m.node_status_waiting
	};

	// A label inside a segment: dark on the coloured ones, the text colour on the pale running one.
	const label = (tone: BandTone) => (tone === 'running' ? 'text-foreground' : 'text-card');
	const columns = $derived(phases.map((phase) => `${phase.width}fr`).join(' '));
	const duration = (step: BandStep) =>
		step.seconds === null ? null : formatDuration(step.seconds);
	const title = (step: BandStep) =>
		[NODE_LABELS[step.node](), duration(step), words[step.tone]()].filter(Boolean).join(' · ');

	// For a screen reader the bar in words: each phase with its time, and the steps that did not
	// end well.
	const description = $derived(
		`${m.run_band({ run })}: ${phases
			.map((phase) => {
				const steps = phase.groups
					.flatMap((group) => group.steps)
					.filter((step) => step.tone !== 'green')
					.map((step) => `${NODE_LABELS[step.node]()} ${words[step.tone]()}`);
				return [
					PHASE_LABELS[phase.phase](),
					phase.carried ? carriedLabel : phaseDuration(phase.phase),
					...steps
				]
					.filter(Boolean)
					.join(' ');
			})
			.join(', ')}`
	);

	/** Whether a group is wide enough for its name inside: its part of the whole bar. */
	function roomy(phase: BandPhase, weight: number): boolean {
		const total = phase.groups.reduce((sum, group) => sum + group.weight, 0);
		return wide && total > 0 && (phase.width * weight) / total >= 0.12;
	}
</script>

<div class="flex flex-col gap-2">
	<div
		role="img"
		aria-label={description}
		class={cn('grid gap-1', wide ? 'h-9' : 'h-8')}
		style:grid-template-columns={columns}
	>
		{#each phases as phase (phase.phase)}
			{#if phase.carried}
				<span
					class="flex min-w-0 items-center rounded-[3px] bg-muted px-2 text-[11px] text-muted-foreground"
					title={`${PHASE_LABELS[phase.phase]()} · ${carriedLabel}`}
				>
					{#if wide}<span class="truncate">{carriedLabel}</span>{/if}
				</span>
			{:else}
				<span class="flex min-w-0 gap-0.5">
					{#each phase.groups as group, index (index)}
						{@const [main, ...beside] = group.steps}
						<span class="flex min-w-[3px] flex-col gap-0.5" style:flex-grow={group.weight}>
							<span
								class={cn(
									'flex min-h-0 w-full flex-1 items-center overflow-hidden rounded-[3px]',
									tones[main.tone]
								)}
								title={title(main)}
							>
								{#if roomy(phase, group.weight) && beside.length === 0}
									<span class={cn('truncate px-2 text-[11px] font-semibold', label(main.tone))}>
										{[NODE_LABELS[main.node](), duration(main)].filter(Boolean).join(' ')}
									</span>
								{:else if roomy(phase, group.weight)}
									<span
										class={cn(
											'truncate px-2 text-[10px] leading-none font-semibold',
											label(main.tone)
										)}
									>
										{[NODE_LABELS[main.node](), duration(main)].filter(Boolean).join(' ')}
									</span>
								{/if}
							</span>
							{#each beside as step (step.node)}
								<span
									class={cn('h-[3px] shrink-0 rounded-full', tones[step.tone])}
									style:width={`${step.share * 100}%`}
									title={title(step)}
								></span>
							{/each}
						</span>
					{/each}
				</span>
			{/if}
		{/each}
	</div>
	{#if wide}
		<div
			class="grid gap-1 text-[11px] text-muted-foreground"
			style:grid-template-columns={columns}
			aria-hidden="true"
		>
			{#each phases as phase (phase.phase)}
				<span class="flex min-w-0 flex-col">
					<span class="truncate font-semibold tracking-wider uppercase">
						{PHASE_LABELS[phase.phase]()}
					</span>
					<span class="truncate whitespace-nowrap tabular-nums">
						{phase.carried ? carriedLabel : (phaseDuration(phase.phase) ?? '')}
					</span>
				</span>
			{/each}
		</div>
	{:else}
		<p class="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground" aria-hidden="true">
			{#each phases as phase (phase.phase)}
				<span class="whitespace-nowrap tabular-nums">
					{PHASE_LABELS[phase.phase]()}
					{phase.carried ? carriedLabel : (phaseDuration(phase.phase) ?? '')}
				</span>
			{/each}
		</p>
	{/if}
</div>
