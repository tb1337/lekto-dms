<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { progress, type NodeState, type Processing } from '#lib/pipeline.ts';
	import { cn } from '#lib/utils.ts';

	// How far the processing of a document is: a segment per node of the graph, in its order,
	// done (by outcome), running (pulsing), waiting or skipped. Nodes run side by side, so the
	// segments say what happens; a percentage would pretend a precision there is none. With
	// `href`, the bar leads to the log.
	let {
		processing,
		href = null,
		compact = false,
		class: className = ''
	}: {
		processing: Processing;
		href?: string | null;
		/** A thin bar without its text (lists, cards). */
		compact?: boolean;
		class?: string;
	} = $props();

	const counted = $derived(progress(processing));
	const now = $derived(
		counted.running.length > 0
			? m.doc_processing({
					node: counted.running.map((node) => NODE_LABELS[node]()).join(', '),
					done: counted.done,
					total: counted.total
				})
			: m.upload_progress({ done: counted.done, total: counted.total })
	);

	function tone(state: NodeState): string {
		switch (state.status) {
			case 'running':
				return 'animate-pulse bg-primary/50';
			case 'skipped':
				return 'bg-muted-foreground/25';
			case 'waiting':
				return 'bg-muted';
			case 'done':
				return state.outcome === 'failed'
					? 'bg-destructive'
					: state.outcome === 'uncertain'
						? 'bg-lane-yellow-foreground'
						: 'bg-primary';
		}
	}

	function stateLabel(state: NodeState): string {
		switch (state.status) {
			case 'waiting':
				return m.node_status_waiting();
			case 'running':
				return m.node_status_running();
			case 'skipped':
				return m.node_status_skipped();
			case 'done':
				return state.outcome === 'failed'
					? m.outcome_failed()
					: state.outcome === 'uncertain'
						? m.outcome_uncertain()
						: m.outcome_ok();
		}
	}
</script>

{#snippet bar()}
	<span
		role="progressbar"
		aria-label={m.processing_progress()}
		aria-valuemin={0}
		aria-valuemax={counted.total}
		aria-valuenow={counted.done}
		aria-valuetext={now}
		class={cn('flex w-full gap-0.5', compact ? 'h-1' : 'h-1.5')}
	>
		{#each processing.nodes as state (state.node)}
			<span
				class={cn('h-full min-w-1 flex-1 rounded-full transition-colors', tone(state))}
				title="{NODE_LABELS[state.node]()}: {stateLabel(state)}"
			></span>
		{/each}
	</span>
{/snippet}

<span class={cn('flex min-w-0 flex-col gap-1', className)}>
	{#if href}
		<a {href} class="block rounded-full py-1 hover:opacity-80" aria-label={now}>
			{@render bar()}
		</a>
	{:else}
		{@render bar()}
	{/if}
	{#if !compact}
		<span class="text-sm text-muted-foreground" role="status">{now}</span>
	{/if}
</span>
