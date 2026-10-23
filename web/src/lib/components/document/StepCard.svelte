<script lang="ts">
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { stepLook, TONE_TEXT, type Tone } from '#lib/step-look.ts';
	import type { Step } from '#lib/steps.ts';
	import { cn } from '#lib/utils.ts';

	// One step of a run as a card, as in the log before: its state by icon and word (not by
	// colour alone), its name, how long it took, what it found in one line, and whether it is
	// an earlier run's. A button: it opens the step's details (`controls`, named while open). `compact` (two cards
	// side by side on a phone): the state and the time go below the name, which keeps its line.
	let {
		step,
		summary,
		duration,
		expanded,
		controls,
		compact = false,
		onclick
	}: {
		step: Step;
		summary: string | null;
		duration: string | null;
		expanded: boolean;
		controls: string;
		compact?: boolean;
		onclick: () => void;
	} = $props();

	const look = $derived(stepLook(step.state));
	const carried = $derived(step.done.from);
	const cards: Record<Tone, string> = {
		running: 'bg-card',
		muted: 'border-dashed bg-card',
		red: 'border-lane-red-mark-edge/40 bg-lane-red/40',
		yellow: 'border-lane-yellow-mark-edge/40 bg-lane-yellow/25',
		green: 'bg-card hover:bg-secondary/40'
	};
	const rings: Record<Tone, string> = {
		running: 'ring-brand',
		muted: 'ring-brand',
		red: 'ring-lane-red-mark-edge',
		yellow: 'ring-lane-yellow-mark-edge',
		green: 'ring-brand'
	};
</script>

<button
	type="button"
	data-node={step.node}
	data-status={step.state?.status ?? 'not_run'}
	aria-expanded={expanded}
	aria-controls={expanded ? controls : undefined}
	{onclick}
	class={cn(
		'flex w-full min-w-0 flex-col gap-1 rounded-2xl border px-3 py-2.5 text-left transition-colors',
		cards[look.tone],
		expanded && ['ring-2', rings[look.tone]]
	)}
>
	<span class="flex w-full min-w-0 items-start gap-2">
		<look.icon
			class={cn(
				'mt-0.5 size-4 shrink-0',
				TONE_TEXT[look.tone],
				look.spin && 'animate-spin',
				carried !== null && 'opacity-60'
			)}
			aria-hidden="true"
			strokeWidth={2.2}
		/>
		<span
			class={cn(
				'min-w-0 text-sm leading-snug font-semibold wrap-break-word hyphens-auto',
				carried !== null && 'text-muted-foreground'
			)}
		>
			{NODE_LABELS[step.node]()}
		</span>
		{#if !compact}
			{#if look.tone !== 'green'}
				<span class={cn('mt-px shrink-0 text-xs', TONE_TEXT[look.tone])}>{look.label}</span>
			{/if}
			<span
				class="mt-px ml-auto shrink-0 text-xs whitespace-nowrap text-muted-foreground tabular-nums"
			>
				{duration ?? ''}
			</span>
		{/if}
	</span>
	{#if compact && (duration || look.tone !== 'green')}
		<span class="flex flex-wrap gap-x-2 pl-6 text-xs">
			{#if look.tone !== 'green'}<span class={TONE_TEXT[look.tone]}>{look.label}</span>{/if}
			{#if duration}
				<span class="whitespace-nowrap text-muted-foreground tabular-nums">{duration}</span>
			{/if}
		</span>
	{/if}
	{#if summary || carried !== null}
		<span class="pl-6 text-xs leading-snug text-muted-foreground">
			{[carried !== null ? m.log_from_run({ run: carried }) : null, summary]
				.filter(Boolean)
				.join(' · ')}
		</span>
	{/if}
</button>
