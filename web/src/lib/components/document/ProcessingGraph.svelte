<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import { tick, type Snippet } from 'svelte';
	import StepCard from '#lib/components/document/StepCard.svelte';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import type { Node } from '#lib/pipeline.ts';
	import { stepLook, TONE_TEXT, type Tone } from '#lib/step-look.ts';
	import { PHASE_LABELS, phaseOf, type Phase, type Step } from '#lib/steps.ts';
	import { cn } from '#lib/utils.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import Eyebrow from '#lib/components/page/Eyebrow.svelte';
	import IconButton from '#lib/components/IconButton.svelte';

	// The steps of a run on a desktop (mock A, Tobi 23.10.2026): the four phases as columns, one
	// after another, their steps as the cards of the log before. A card opens its details in a
	// panel right below, with a point towards the card's column.
	let {
		groups,
		run,
		selected,
		summaryOf,
		durationOf,
		phaseDuration,
		highlighted = null,
		onhighlight,
		ontoggle,
		details
	}: {
		groups: readonly { phase: Phase; steps: Step[] }[];
		run: number;
		selected: Node | null;
		summaryOf: (step: Step) => string | null;
		durationOf: (step: Step) => string | null;
		phaseDuration: (steps: readonly Step[]) => string | null;
		/** The step pointed at or focused, here or in the band. */
		highlighted?: Node | null;
		onhighlight: (node: Node | null) => void;
		ontoggle: (node: Node) => void | Promise<void>;
		details: Snippet<[Step]>;
	} = $props();

	const PANEL = 'step-details';
	let section = $state<HTMLElement | null>(null);

	/** Close the panel with its own button: the focus goes back to the step's card, which stays
	 * (the button itself goes with the panel). */
	async function close(node: Node) {
		await ontoggle(node);
		await tick();
		section?.querySelector<HTMLElement>(`[data-node="${node}"]`)?.focus();
	}
	// An arrow between two phases.
	const GAP = '1.125rem';

	const columns = $derived(groups.map(() => 'minmax(0,1fr)').join(` ${GAP} `));
	const open = $derived(
		groups.flatMap((group) => group.steps).find((step) => step.node === selected) ?? null
	);
	const look = $derived(stepLook(open?.state ?? null));
	// The point of the panel: the middle of the open card's column.
	const point = $derived.by(() => {
		if (!open) return '0px';
		const count = groups.length;
		const index = groups.findIndex((group) => group.phase === phaseOf(open.node));
		return `calc((100% - ${count - 1} * ${GAP}) * ${(2 * index + 1) / (2 * count)} + ${index} * ${GAP} - 0.4rem)`;
	});
	const borders: Record<Tone, string> = {
		green: 'border-border',
		running: 'border-border',
		muted: 'border-border',
		yellow: 'border-lane-yellow-foreground/35',
		red: 'border-lane-red-foreground/35'
	};
	const tints: Record<Tone, string> = {
		green: 'bg-secondary/40',
		running: 'bg-secondary/40',
		muted: 'bg-secondary/40',
		yellow: 'bg-lane-yellow/60',
		red: 'bg-lane-red/60'
	};
</script>

<Card.Root
	as="section"
	bind:ref={section}
	aria-labelledby="steps-heading"
	class="flex min-w-0 flex-col gap-3.5"
>
	<SectionTitle size="card" id="steps-heading">
		{m.processing_steps()} · {m.log_run({ run })}
	</SectionTitle>
	<div class="grid items-start" style:grid-template-columns={columns}>
		{#each groups as group, index (group.phase)}
			{#if index > 0}
				<div class="flex justify-center pt-7 text-muted-foreground/60" aria-hidden="true">
					<ChevronRight class="size-4" />
				</div>
			{/if}
			<div class="flex min-w-0 flex-col gap-2">
				<Eyebrow as="h3" class="whitespace-nowrap">
					{PHASE_LABELS[group.phase]()}{#if phaseDuration(group.steps)}<span
							class="tracking-normal normal-case">{` · ${phaseDuration(group.steps)}`}</span
						>{/if}
				</Eyebrow>
				{#each group.steps as step (step.node)}
					<StepCard
						{step}
						summary={summaryOf(step)}
						duration={durationOf(step)}
						expanded={step.node === selected}
						highlighted={step.node === highlighted}
						onhighlight={(on) => onhighlight(on ? step.node : null)}
						controls={PANEL}
						onclick={() => ontoggle(step.node)}
					/>
				{/each}
			</div>
		{/each}
	</div>
	{#if open}
		<div
			id={PANEL}
			class={cn(
				'relative mt-1.5 flex flex-col gap-3 rounded-2xl border p-4',
				borders[look.tone],
				tints[look.tone]
			)}
		>
			<!-- The point: the card's ground, tinted like the panel. -->
			<span
				class={cn(
					'absolute -top-[0.45rem] size-3 rotate-45 overflow-hidden border-t border-l bg-card',
					borders[look.tone]
				)}
				style:left={point}
				aria-hidden="true"
			>
				<span class={cn('absolute inset-0', tints[look.tone])}></span>
			</span>
			<div class="flex items-center gap-2.5">
				<look.icon
					class={cn('size-4.5 shrink-0', TONE_TEXT[look.tone], look.spin && 'animate-spin')}
					aria-hidden="true"
					strokeWidth={2.2}
				/>
				<SectionTitle size="card" level={3}>{NODE_LABELS[open.node]()}</SectionTitle>
				<span class={cn('text-sm', TONE_TEXT[look.tone])}>{look.label}</span>
				<IconButton
					size="sm"
					class="ml-auto text-muted-foreground"
					label={m.run_close_details()}
					onclick={() => close(open.node)}
				>
					<ChevronUp aria-hidden="true" />
				</IconButton>
			</div>
			{@render details(open)}
		</div>
	{/if}
</Card.Root>
