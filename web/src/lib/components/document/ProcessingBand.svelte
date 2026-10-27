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
	import { MARK, ON_MARK, STRIPE } from '#lib/step-look.ts';
	import { PHASE_LABELS, type Phase } from '#lib/steps.ts';
	import { cn } from '#lib/utils.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import type { Tone } from '#lib/tones.ts';

	// The run in one bar (`band`): the phases side by side by how long they took, the steps by
	// their duration and colour, the steps that ran beside the longest one as thin stripes below
	// it, the steps an earlier run did muted. Wide, the phases' names stand below their part of
	// the bar; narrow, in one line. A label stands inside a segment only where it fits whole.
	// The colours are the lane chips' (Tobi, 23.10.2026). Each segment is a button for its step:
	// pointed at or focused, here or at its card (`highlighted`), it stays lit while the others
	// step back, a ring in its colour around it, a bracket below it spanning it, and the reading
	// line under the bar tells what it did; nothing grows or covers a neighbour. A click opens
	// the step.
	let {
		phases,
		run,
		wide,
		phaseDuration,
		noteOf,
		reading,
		idle = null,
		highlighted = null,
		expanded = null,
		onhighlight,
		onselect
	}: {
		phases: readonly BandPhase[];
		run: number;
		wide: boolean;
		phaseDuration: (phase: Phase) => string | null;
		/** How a step that did not end OK by itself came to count as OK, for its words. */
		noteOf: (node: Node) => string | null;
		/** What the reading line tells of a step besides its name, state and time. */
		reading: (node: Node) => string | null;
		/** The reading line while no step is lit. */
		idle?: string | null;
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
		running: 'animate-pulse bg-lane-running ring-1 ring-inset ring-lane-running-foreground/35',
		waiting:
			'border border-dashed border-muted-foreground/60 bg-[repeating-linear-gradient(45deg,var(--color-muted)_0_4px,transparent_4px_8px)]',
		carried: 'bg-muted ring-1 ring-inset ring-border'
	};
	const stripes: Record<BandTone, string> = {
		green: STRIPE.green,
		yellow: STRIPE.yellow,
		red: STRIPE.red,
		running: 'animate-pulse bg-lane-running-foreground/50',
		waiting: 'bg-muted-foreground/30',
		carried: 'bg-muted-foreground/25'
	};
	// The ring of the lit segment, in its colour.
	const rings: Record<BandTone, string> = {
		green: 'ring-lane-green-foreground',
		yellow: 'ring-lane-yellow-foreground',
		red: 'ring-lane-red-foreground',
		running: 'ring-lane-running-foreground',
		waiting: 'ring-muted-foreground',
		carried: 'ring-muted-foreground'
	};
	const brackets: Record<BandTone, string> = {
		green: 'border-lane-green-foreground',
		yellow: 'border-lane-yellow-foreground',
		red: 'border-lane-red-foreground',
		running: 'border-lane-running-foreground',
		waiting: 'border-muted-foreground',
		carried: 'border-muted-foreground'
	};
	// The state in the reading line, as the badge of its lane.
	const BADGE_TONE: Record<BandTone, Tone> = {
		green: 'green',
		yellow: 'yellow',
		red: 'red',
		running: 'running',
		waiting: 'muted',
		carried: 'muted'
	};
	const words: Record<Exclude<BandTone, 'carried'>, () => string> = {
		green: m.outcome_ok,
		yellow: m.outcome_uncertain,
		red: m.outcome_failed,
		running: m.node_status_running,
		waiting: m.node_status_waiting
	};

	// A label inside a segment: the chip's text on its ground, the text colour on the running one.
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
	const litPhase = $derived(
		lit === null
			? null
			: (phases.find((phase) =>
					phase.groups.some((group) => group.steps.some((step) => step.node === lit.node))
				)?.phase ?? null)
	);

	// The bracket below the lit segment: exactly its span.
	let frame = $state<HTMLElement | null>(null);
	let span = $state<{ left: number; width: number } | null>(null);
	$effect(() => {
		const node = lit?.node;
		void width;
		if (!node || !frame) {
			span = null;
			return;
		}
		void tick().then(() => {
			const segment = frame?.querySelector<HTMLElement>(`[data-band-node="${node}"]`);
			if (!frame || !segment) return;
			const outer = frame.getBoundingClientRect();
			const own = segment.getBoundingClientRect();
			span = { left: own.left - outer.left, width: own.width };
		});
	});
</script>

{#snippet segment(step: BandStep, text: string | null, stripe: boolean)}
	{@const on = step.node === highlighted}
	<button
		type="button"
		data-band-node={step.node}
		data-lit={on ? '' : undefined}
		aria-label={[title(step), reading(step.node)].filter(Boolean).join(' · ')}
		aria-expanded={step.node === expanded}
		class={cn(
			'relative flex min-w-0 items-center overflow-hidden rounded-xs outline-none motion-safe:transition-opacity motion-safe:duration-150',
			'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card',
			stripe
				? ['h-[3px] shrink-0', stripes[step.tone]]
				: ['min-h-0 w-full flex-1', tones[step.tone]],
			!stripe && step.overruled && 'ring-2 ring-lane-yellow-foreground/60 ring-inset',
			lit !== null && !on && 'opacity-35',
			on && !stripe && ['ring-2 ring-inset', rings[step.tone]]
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
					'px-2 text-micro whitespace-nowrap',
					on ? 'font-bold' : 'font-semibold',
					label(step.tone)
				)}
				aria-hidden="true"
			>
				{text}
			</span>
		{/if}
	</button>
{/snippet}

<div class="relative flex flex-col" bind:this={frame}>
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
	<!-- The bracket below the lit segment, and the reading line it points at: their room is
	     always kept, so that nothing moves when a step lights up. -->
	<div class="relative h-2.5" aria-hidden="true">
		{#if lit && span}
			<span
				data-band-bracket
				class={cn(
					'absolute top-[3px] h-1.5 rounded-b border-[1.5px] border-t-0',
					brackets[lit.tone]
				)}
				style:left={`${span.left}px`}
				style:width={`${span.width}px`}
			>
				<span
					class={cn(
						'absolute top-full left-1/2 h-1 w-0 -translate-x-1/2 border-l-[1.5px]',
						brackets[lit.tone]
					)}
				></span>
			</span>
		{/if}
	</div>
	<p
		data-band-reading
		class="flex h-6 min-w-0 items-center gap-2 overflow-hidden text-meta whitespace-nowrap text-muted-foreground"
		aria-hidden="true"
	>
		{#if lit}
			<Badge variant={BADGE_TONE[lit.tone]} class="shrink-0">{word(lit)}</Badge>
			<strong class="shrink-0 font-semibold text-foreground">{NODE_LABELS[lit.node]()}</strong>
			{#if duration(lit)}<span class="shrink-0 tabular-nums">· {duration(lit)}</span>{/if}
			{#if reading(lit.node)}
				<span class="min-w-0 truncate text-foreground/85">· {reading(lit.node)}</span>
			{/if}
		{:else if idle}
			<span class="truncate">{idle}</span>
		{/if}
	</p>
	{#if wide}
		<div
			class="mt-1.5 grid gap-1 text-micro text-muted-foreground"
			style:grid-template-columns={columns}
			aria-hidden="true"
		>
			{#each phases as phase (phase.phase)}
				<span
					class={cn(
						'flex min-w-0 flex-col motion-safe:transition-opacity',
						litPhase !== null && (litPhase === phase.phase ? 'text-foreground' : 'opacity-50')
					)}
				>
					<span
						class={cn(
							'tracking-wider whitespace-nowrap uppercase',
							litPhase === phase.phase ? 'font-bold' : 'font-semibold'
						)}
					>
						{PHASE_LABELS[phase.phase]()}
					</span>
					<span class="wrap-break-word tabular-nums">{phaseNote(phase)}</span>
				</span>
			{/each}
		</div>
	{:else}
		<p
			class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground"
			aria-hidden="true"
		>
			{#each phases as phase (phase.phase)}
				<span class="whitespace-nowrap tabular-nums">
					{PHASE_LABELS[phase.phase]()}
					{phaseNote(phase)}
				</span>
			{/each}
		</p>
	{/if}
</div>
