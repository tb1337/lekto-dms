<script lang="ts">
	import {
		GROUP_GAP,
		PHASE_GAP,
		groupWidths,
		labelFor,
		minimumsOf,
		textWidth,
		widthsOf,
		type BandPhase,
		type BandStep,
		type BandTone
	} from '#lib/band.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import type { Node } from '#lib/pipeline.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { PHASE_LABELS, type Phase } from '#lib/steps.ts';
	import { cn } from '#lib/utils.ts';

	// The run in one bar (`band`): the phases side by side by how long they took, the steps by
	// their duration and colour, the steps that ran beside the longest one as thin stripes below
	// it, the steps an earlier run did muted. Wide, the phases' names stand below their part of
	// the bar; narrow, in one line. A label stands inside a segment only where it fits whole.
	let {
		phases,
		run,
		wide,
		phaseDuration,
		noteOf
	}: {
		phases: readonly BandPhase[];
		run: number;
		wide: boolean;
		phaseDuration: (phase: Phase) => string | null;
		/** How a step that did not end OK by itself came to count as OK, for its tooltip. */
		noteOf: (node: Node) => string | null;
	} = $props();

	const tones: Record<BandTone, string> = {
		green: 'bg-lane-green-foreground/80',
		yellow: 'bg-lane-yellow-foreground',
		red: 'bg-lane-red-foreground',
		running: 'animate-pulse bg-lane-running-foreground/50',
		waiting:
			'border border-dashed border-muted-foreground/60 bg-[repeating-linear-gradient(45deg,var(--color-muted)_0_4px,transparent_4px_8px)]',
		carried: 'bg-muted-foreground/25'
	};
	const words: Record<Exclude<BandTone, 'carried'>, () => string> = {
		green: m.outcome_ok,
		yellow: m.outcome_uncertain,
		red: m.outcome_failed,
		running: m.node_status_running,
		waiting: m.node_status_waiting
	};

	// A label inside a segment: dark on the coloured ones, the text colour on the pale running one.
	const label = (tone: BandTone) => (tone === 'running' ? 'text-foreground' : 'text-card');

	let width = $state(0);
	// Each phase keeps room for its name below the bar (wide) and a part of its own.
	const labels = $derived(
		phases.map((phase) =>
			wide ? textWidth(PHASE_LABELS[phase.phase](), 11, true) + PHASE_GAP * 2 : 0
		)
	);
	const widths = $derived(
		widthsOf(
			phases.map((phase) => phase.weight),
			minimumsOf(phases, width, labels)
		)
	);
	const columns = $derived(widths.map((part) => `${part}fr`).join(' '));
	const room = $derived(Math.max(0, width - PHASE_GAP * Math.max(0, phases.length - 1)));

	const fromLabel = (from: number | null) =>
		from === null ? m.run_count_carried_earlier() : m.log_from_run({ run: from });
	const duration = (step: BandStep) =>
		step.seconds === null ? null : formatDuration(step.seconds);
	// How a step stands in words: how it ended (or came to count as OK), or where it is from.
	function word(step: BandStep): string {
		if (step.tone === 'carried') return fromLabel(step.from);
		return (step.overruled ? noteOf(step.node) : null) ?? words[step.tone]();
	}
	const title = (step: BandStep) =>
		[NODE_LABELS[step.node](), duration(step), word(step)].filter(Boolean).join(' · ');
	function inside(step: BandStep, px: number, size: number): string | null {
		if (step.tone === 'carried' || step.tone === 'waiting') return null;
		return labelFor(NODE_LABELS[step.node](), duration(step), px, size);
	}
	const phaseNote = (phase: BandPhase) =>
		phase.carried ? fromLabel(phase.from) : (phaseDuration(phase.phase) ?? '');

	// For a screen reader the bar in words: each phase with its time or where it is from, and
	// the steps of the run that did not end well.
	const description = $derived(
		`${m.run_band({ run })}: ${phases
			.map((phase) => {
				const steps = phase.groups
					.flatMap((group) => group.steps)
					.filter((step) => step.tone !== 'green' && step.tone !== 'carried')
					.map((step) => `${NODE_LABELS[step.node]()} ${word(step)}`);
				return [PHASE_LABELS[phase.phase](), phaseNote(phase), ...steps].filter(Boolean).join(' ');
			})
			.join(', ')}`
	);
</script>

<div class="flex flex-col gap-2">
	<div
		role="img"
		aria-label={description}
		class={cn('grid gap-1', wide ? 'h-9' : 'h-8')}
		style:grid-template-columns={columns}
		bind:clientWidth={width}
	>
		{#each phases as phase, phaseIndex (phase.phase)}
			{@const sizes = groupWidths(widths[phaseIndex] * room, phase.groups)}
			<span class="flex min-w-0" style:gap={`${GROUP_GAP}px`}>
				{#each phase.groups as group, index (index)}
					{@const [main, ...beside] = group.steps}
					{@const text = inside(main, sizes[index], beside.length === 0 ? 11 : 10)}
					<span
						class="flex min-w-0 flex-col gap-0.5"
						style:flex={`${group.grow} 1 ${group.basis}px`}
					>
						<span
							class={cn(
								'flex min-h-0 w-full flex-1 items-center overflow-hidden rounded-[3px]',
								tones[main.tone],
								main.overruled && 'ring-1 ring-lane-yellow-foreground/70 ring-inset'
							)}
							title={title(main)}
						>
							{#if text}
								<span
									class={cn(
										'px-2 font-semibold whitespace-nowrap',
										beside.length === 0 ? 'text-[11px]' : 'text-[10px] leading-none',
										label(main.tone)
									)}
								>
									{text}
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
					<span class="font-semibold tracking-wider whitespace-nowrap uppercase">
						{PHASE_LABELS[phase.phase]()}
					</span>
					<span class="wrap-break-word tabular-nums">{phaseNote(phase)}</span>
				</span>
			{/each}
		</div>
	{:else}
		<p class="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground" aria-hidden="true">
			{#each phases as phase (phase.phase)}
				<span class="whitespace-nowrap tabular-nums">
					{PHASE_LABELS[phase.phase]()}
					{phaseNote(phase)}
				</span>
			{/each}
		</p>
	{/if}
</div>
