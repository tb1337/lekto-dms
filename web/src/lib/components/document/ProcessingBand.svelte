<script lang="ts">
	import { tick } from 'svelte';
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
	import { MARK, ON_MARK } from '#lib/step-look.ts';
	import { PHASE_LABELS, type Phase } from '#lib/steps.ts';
	import { cn } from '#lib/utils.ts';

	// The run in one bar (`band`): the phases side by side by how long they took, the steps by
	// their duration and colour, the steps that ran beside the longest one as thin stripes below
	// it, the steps an earlier run did muted. Wide, the phases' names stand below their part of
	// the bar; narrow, in one line. A label stands inside a segment only where it fits whole.
	// Each segment is a button for its step (Tobi, 23.10.2026): pointing at it or focusing it
	// lights it up, with its name, time and state above the bar, and lights up the step's card;
	// a card pointed at lights up its segment (`highlighted`); a click opens the step.
	let {
		phases,
		run,
		wide,
		phaseDuration,
		noteOf,
		highlighted = null,
		expanded = null,
		onhighlight,
		onselect
	}: {
		phases: readonly BandPhase[];
		run: number;
		wide: boolean;
		phaseDuration: (phase: Phase) => string | null;
		/** How a step that did not end OK by itself came to count as OK, for its tooltip. */
		noteOf: (node: Node) => string | null;
		/** The step pointed at or focused, here or at its card. */
		highlighted?: Node | null;
		/** The step whose details are open. */
		expanded?: Node | null;
		onhighlight: (node: Node | null) => void;
		onselect: (node: Node) => void;
	} = $props();

	const tones: Record<BandTone, string> = {
		green: MARK.green,
		yellow: MARK.yellow,
		red: MARK.red,
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

	// A label inside a segment: the lane's text on its mark, the text colour on the pale running one.
	const label = (tone: BandTone) =>
		tone === 'green' || tone === 'yellow' || tone === 'red' ? ON_MARK[tone] : 'text-foreground';

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
	// the steps of the run that did not end well; each segment tells its own step.
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

	const steps = $derived(phases.flatMap((phase) => phase.groups.flatMap((group) => group.steps)));
	const lit = $derived(steps.find((step) => step.node === highlighted) ?? null);

	// The label above the lit segment: over its middle, or flush with its edge near the ends of
	// the bar, so that it is never cut.
	let frame = $state<HTMLElement | null>(null);
	let tip = $state<{ x: number; align: 'start' | 'center' | 'end' } | null>(null);
	$effect(() => {
		const node = lit?.node;
		void width;
		if (!node || !frame) {
			tip = null;
			return;
		}
		void tick().then(() => {
			const segment = frame?.querySelector<HTMLElement>(`[data-band-node="${node}"]`);
			if (!frame || !segment) return;
			const outer = frame.getBoundingClientRect();
			const own = segment.getBoundingClientRect();
			const middle = own.left + own.width / 2 - outer.left;
			if (middle < outer.width * 0.2) tip = { x: own.left - outer.left, align: 'start' };
			else if (middle > outer.width * 0.8) tip = { x: own.right - outer.left, align: 'end' };
			else tip = { x: middle, align: 'center' };
		});
	});
</script>

{#snippet segment(step: BandStep, text: string | null, stripe: boolean)}
	{@const on = step.node === highlighted}
	<button
		type="button"
		data-band-node={step.node}
		data-lit={on ? '' : undefined}
		aria-label={title(step)}
		aria-expanded={step.node === expanded}
		class={cn(
			'relative flex min-w-0 items-center overflow-hidden rounded-[3px] outline-none motion-safe:transition-[transform,box-shadow] motion-safe:duration-150',
			'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card',
			stripe ? 'h-[3px] shrink-0' : 'min-h-0 w-full flex-1',
			tones[step.tone],
			step.overruled && 'ring-2 ring-lane-yellow-mark ring-inset',
			on && ['z-10 shadow-md', stripe ? 'scale-y-[2.5]' : 'scale-y-[1.35]']
		)}
		style:width={stripe ? `${step.share * 100}%` : undefined}
		onmouseenter={() => onhighlight(step.node)}
		onmouseleave={() => onhighlight(null)}
		onfocus={() => onhighlight(step.node)}
		onblur={() => onhighlight(null)}
		onclick={() => onselect(step.node)}
	>
		{#if text}
			<span
				class={cn(
					'px-2 text-[11px] font-semibold whitespace-nowrap',
					label(step.tone),
					on && 'opacity-0'
				)}
				aria-hidden="true"
			>
				{text}
			</span>
		{/if}
	</button>
{/snippet}

<div class="relative flex flex-col gap-2" bind:this={frame}>
	{#if lit && tip}
		<span
			class={cn(
				'pointer-events-none absolute -top-2 z-20 -translate-y-full rounded-md border bg-popover px-2 py-1 text-xs whitespace-nowrap text-popover-foreground shadow-md',
				tip.align === 'center' && '-translate-x-1/2',
				tip.align === 'end' && '-translate-x-full'
			)}
			style:left={`${tip.x}px`}
			aria-hidden="true"
		>
			{title(lit)}
		</span>
	{/if}
	<div
		role="group"
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
					<span
						class="flex min-w-0 flex-col gap-0.5"
						style:flex={`${group.grow} 1 ${group.basis}px`}
					>
						{@render segment(main, inside(main, sizes[index], 11), false)}
						{#each beside as step (step.node)}
							{@render segment(step, null, true)}
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
