<script lang="ts">
	import Circle from '@lucide/svelte/icons/circle';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import CircleDashed from '@lucide/svelte/icons/circle-dashed';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import OctagonX from '@lucide/svelte/icons/octagon-x';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { onMount } from 'svelte';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import {
		durationSeconds,
		levels,
		type GraphNode,
		type Node,
		type NodeState,
		type Processing
	} from '#lib/pipeline.ts';
	import { cn } from '#lib/utils.ts';

	// Where the processing of a document stands: every node of the graph with its state, in rows
	// by level (nodes that run side by side share a row), live with the events.
	let { processing, graph }: { processing: Processing; graph: readonly GraphNode[] } = $props();

	const nodeLabel: Record<Node, () => string> = {
		receive: m.node_receive,
		ocr: m.node_ocr,
		pages: m.node_pages,
		parse: m.node_parse,
		classify: m.node_classify,
		extract_fields: m.node_extract_fields,
		apply_rules: m.node_apply_rules,
		file: m.node_file
	};

	const states = $derived(new Map(processing.nodes.map((state) => [state.node, state])));
	const rows = $derived(
		graph.length > 0 ? levels(graph) : processing.nodes.map((state) => [state.node])
	);

	// The clock for the duration of a running node.
	let now = $state(new Date());
	onMount(() => {
		const timer = setInterval(() => (now = new Date()), 1000);
		return () => clearInterval(timer);
	});

	function look(state: NodeState) {
		if (state.status === 'running')
			return { icon: LoaderCircle, label: m.node_status_running(), tone: 'running', spin: true };
		if (state.status === 'skipped')
			return { icon: CircleDashed, label: m.node_status_skipped(), tone: 'muted', spin: false };
		if (state.status === 'waiting')
			return { icon: Circle, label: m.node_status_waiting(), tone: 'muted', spin: false };
		if (state.outcome === 'failed')
			return { icon: OctagonX, label: m.outcome_failed(), tone: 'red', spin: false };
		if (state.outcome === 'uncertain')
			return { icon: TriangleAlert, label: m.outcome_uncertain(), tone: 'yellow', spin: false };
		return { icon: CircleCheck, label: m.outcome_ok(), tone: 'green', spin: false };
	}

	const tones: Record<string, string> = {
		running: 'bg-lane-running text-lane-running-foreground',
		muted: 'bg-card text-muted-foreground',
		red: 'bg-lane-red text-lane-red-foreground',
		yellow: 'bg-lane-yellow text-lane-yellow-foreground',
		green: 'bg-lane-green text-lane-green-foreground'
	};

	function duration(state: NodeState): string | null {
		const seconds = durationSeconds(state, now);
		if (seconds === null) return null;
		return formatNumber(seconds, {
			style: 'unit',
			unit: 'second',
			unitDisplay: 'narrow',
			maximumFractionDigits: seconds < 10 ? 1 : 0
		});
	}
</script>

<ol class="flex flex-col gap-1.5" aria-label={m.graph_title()}>
	{#each rows as row, index (index)}
		<li class="flex flex-wrap gap-1.5">
			{#each row as node (node)}
				{@const state = states.get(node)}
				{#if state}
					{@const shown = look(state)}
					<span
						data-node={node}
						data-status={state.status}
						data-outcome={state.outcome}
						class={cn(
							'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[0.8125rem] whitespace-nowrap',
							tones[shown.tone]
						)}
						title={shown.label}
					>
						<shown.icon
							class={cn('size-[15px] shrink-0', shown.spin && 'animate-spin')}
							aria-hidden="true"
							strokeWidth={2.2}
						/>
						<span class="font-semibold">{nodeLabel[node]()}</span>
						<span class="sr-only">{shown.label}</span>
						{#if duration(state) !== null}
							<span class="text-xs opacity-80">{duration(state)}</span>
						{/if}
					</span>
				{/if}
			{/each}
		</li>
	{/each}
</ol>
