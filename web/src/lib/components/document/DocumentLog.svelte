<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Circle from '@lucide/svelte/icons/circle';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import CircleDashed from '@lucide/svelte/icons/circle-dashed';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import MessageSquareCode from '@lucide/svelte/icons/message-square-code';
	import OctagonX from '@lucide/svelte/icons/octagon-x';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { onMount, untrack } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import PromptDialog from '#lib/components/document/PromptDialog.svelte';
	import TokenInfo from '#lib/components/document/TokenInfo.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import {
		durationSeconds,
		levels,
		reprocessable,
		type GraphNode,
		type Node,
		type NodeState
	} from '#lib/pipeline.ts';
	import { usageOf } from '#lib/usage.ts';
	import { cn } from '#lib/utils.ts';

	type Document = components['schemas']['DocumentDetails'];
	type LogEntry = components['schemas']['LogEntry'];
	type Exchange = components['schemas']['RunExchangeOut'];
	type ExchangeNode = components['schemas']['ExchangeNode'];
	type Outcome = components['schemas']['Outcome'];

	// The processing of a document: every node of the graph in a row by level (nodes that run
	// side by side share one), with its state and duration, live with the events; below each
	// what it did in every run (owner and admins), with the model's token figures and prompt.
	let {
		document,
		graph,
		manageable,
		onreprocess
	}: {
		document: Document;
		graph: readonly GraphNode[];
		manageable: boolean;
		onreprocess: () => void;
	} = $props();

	// The nodes that ask the language model and keep what they sent.
	const MODEL_NODES: readonly ExchangeNode[] = ['signal_llm', 'fields'];

	let entries = $state<LogEntry[] | null>(null);
	let exchanges = $state<Partial<Record<Node, Exchange[]>>>({});
	let problem = $state<string | null>(null);
	let prompt = $state<{ title: string; meta: string; calls: Exchange['calls'] } | null>(null);
	let promptOpen = $state(false);

	// An answer for a document the view has left behind, or one overtaken by a later request,
	// must not replace the current entries.
	let latest = 0;
	async function load() {
		if (!manageable) return;
		const wanted = document.id;
		const request = ++latest;
		try {
			const [log, ...kept] = await Promise.all([
				unwrap(api.GET('/api/v1/documents/{id}/log', { params: { path: { id: wanted } } })),
				...MODEL_NODES.map((node) =>
					unwrap(
						api.GET('/api/v1/documents/{id}/exchanges/{node}', {
							params: { path: { id: wanted, node } }
						})
					)
				)
			]);
			if (wanted !== document.id || request !== latest) return;
			entries = log;
			exchanges = Object.fromEntries(MODEL_NODES.map((node, index) => [node, kept[index]]));
			problem = null;
		} catch (error) {
			if (wanted === document.id && request === latest) problem = describeError(error);
		}
	}

	// Loaded once per document and after each completed node; a new state of the document
	// (every event) does not load it again.
	const documentId = $derived(document.id);
	let loadedFor = '';
	$effect(() => {
		const id = documentId;
		void events.generation;
		untrack(() => {
			if (loadedFor !== id) {
				entries = null;
				problem = null;
				loadedFor = id;
			}
			void load();
		});
		return events.subscribe((event) => {
			if (event.document_id === id && event.type === 'document.node_completed') void load();
		});
	});

	// The clock for the duration of a running node.
	let now = $state(new Date());
	onMount(() => {
		const timer = setInterval(() => (now = new Date()), 1000);
		return () => clearInterval(timer);
	});

	const states = $derived(new Map(document.processing.nodes.map((state) => [state.node, state])));
	const rows = $derived(
		graph.length > 0 ? levels(graph) : document.processing.nodes.map((state) => [state.node])
	);
	// The runs of each node, the latest first.
	const runs = $derived.by(() => {
		const byNode: Partial<Record<Node, LogEntry[]>> = {};
		for (const entry of entries ?? []) (byNode[entry.node] ??= []).unshift(entry);
		return byNode;
	});

	const outcomeLabel: Record<Outcome, () => string> = {
		ok: m.outcome_ok,
		uncertain: m.outcome_uncertain,
		failed: m.outcome_failed
	};

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

	const cards: Record<string, string> = {
		running: 'bg-card',
		muted: 'border-dashed bg-card',
		red: 'border-lane-red-foreground/30 bg-lane-red/40',
		yellow: 'border-lane-yellow-foreground/25 bg-lane-yellow/25',
		green: 'bg-card'
	};
	const texts: Record<string, string> = {
		running: 'text-lane-running-foreground',
		muted: 'text-muted-foreground',
		red: 'text-lane-red-foreground',
		yellow: 'text-lane-yellow-foreground',
		green: 'text-lane-green-foreground'
	};

	const seconds = (value: number, digits = 1) =>
		formatNumber(value, {
			style: 'unit',
			unit: 'second',
			unitDisplay: 'narrow',
			maximumFractionDigits: digits
		});

	function duration(state: NodeState): string | null {
		const value = durationSeconds(state, now);
		return value === null ? null : seconds(value, value < 10 ? 1 : 0);
	}

	const time = (value: string) => formatDate(value, { timeStyle: 'medium' });

	function exchangeOf(entry: LogEntry): Exchange | undefined {
		return exchanges[entry.node]?.find((exchange) => exchange.run === entry.run);
	}

	function showPrompt(entry: LogEntry, exchange: Exchange) {
		prompt = {
			title: m.prompt_title({ node: NODE_LABELS[entry.node]() }),
			meta: [entry.model_version, time(entry.started_at), m.log_run({ run: entry.run })]
				.filter(Boolean)
				.join(' · '),
			calls: exchange.calls
		};
		promptOpen = true;
	}

	// The current run at a glance: when it began, how long it took, the model's tokens.
	const current = $derived(document.processing.nodes);
	const started = $derived(
		current
			.map((state) => state.started_at)
			.filter((value): value is string => value !== null)
			.sort()[0] ?? null
	);
	const finished = $derived(
		current
			.map((state) => state.finished_at)
			.filter((value): value is string => value !== null)
			.sort()
			.at(-1) ?? null
	);
	const tokens = $derived.by(() => {
		let input = 0;
		let output = 0;
		let any = false;
		for (const entry of entries ?? []) {
			if (entry.run !== document.processing.run) continue;
			const usage = usageOf(entry.output);
			if (!usage) continue;
			any = true;
			input += usage.input ?? 0;
			output += usage.output ?? 0;
		}
		return any ? { input, output } : null;
	});
	const statusLabel: Record<Document['processing']['status'], () => string> = {
		processing: m.lane_running,
		review: m.lane_yellow,
		failed: m.outcome_failed,
		completed: m.lane_green
	};
	const canReprocess = $derived(
		manageable &&
			document.processing.status !== 'processing' &&
			reprocessable(graph, document.processing).some((node) => node !== 'receive')
	);
</script>

<div class="flex flex-wrap items-start gap-6">
	<section aria-labelledby="log-heading" class="flex min-w-0 flex-[999_1_560px] flex-col gap-2.5">
		<h2
			id="log-heading"
			class="text-xs font-semibold tracking-wider text-muted-foreground uppercase"
		>
			{m.graph_title()} · {m.log_run({ run: document.processing.run })}
		</h2>
		{#if problem}<p class="text-destructive" role="alert">{problem}</p>{/if}
		<ol class="flex flex-col gap-2.5">
			{#each rows as row, rowIndex (rowIndex)}
				<li class="flex flex-wrap gap-2.5">
					{#each row as node (node)}
						{@const state = states.get(node)}
						{#if state}
							{@const shown = look(state)}
							{@const done = runs[node] ?? []}
							<details
								open={state.outcome === 'uncertain' || state.outcome === 'failed'}
								data-node={node}
								data-status={state.status}
								class={cn(
									'group min-w-[15rem] flex-1 rounded-2xl border px-4 py-3',
									cards[shown.tone]
								)}
							>
								<summary
									class="flex cursor-pointer list-none items-center gap-2.5 [&::-webkit-details-marker]:hidden"
								>
									<shown.icon
										class={cn(
											'size-[18px] shrink-0',
											texts[shown.tone],
											shown.spin && 'animate-spin'
										)}
										aria-hidden="true"
										strokeWidth={2.2}
									/>
									<span class="font-semibold">{NODE_LABELS[node]()}</span>
									<span class={cn('text-sm', texts[shown.tone])}>{shown.label}</span>
									<span class="ml-auto text-sm text-muted-foreground tabular-nums">
										{duration(state) ?? ''}
									</span>
									<ChevronDown
										class="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
										aria-hidden="true"
									/>
								</summary>
								{#if !manageable}
									<p class="mt-2 ml-7 text-sm text-muted-foreground">{m.log_owner_only()}</p>
								{:else if done.length === 0}
									<p class="mt-2 ml-7 text-sm text-muted-foreground">
										{entries === null ? m.loading() : m.log_none()}
									</p>
								{/if}
								{#each done as entry (`${entry.run}-${entry.started_at}`)}
									{@const usage = usageOf(entry.output)}
									{@const exchange = exchangeOf(entry)}
									<div class="mt-2.5 ml-7 flex flex-col gap-1.5 text-sm" data-run={entry.run}>
										<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
											<span>
												{time(entry.started_at)} · {m.log_run({
													run: entry.run
												})}{#if entry.model_version}
													· {entry.model_version}{/if}
											</span>
											{#if usage}
												<TokenInfo
													{usage}
													model={entry.model_version}
													id="tokens-{entry.node}-{entry.run}"
												/>
											{/if}
											{#if exchange}
												<Button
													variant="outline"
													size="sm"
													class="ml-auto"
													aria-haspopup="dialog"
													onclick={() => showPrompt(entry, exchange)}
												>
													<MessageSquareCode aria-hidden="true" />
													{m.prompt_open()}
												</Button>
											{/if}
										</div>
										<dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
											<dt class="text-muted-foreground">{m.log_outcome()}</dt>
											<dd>
												{outcomeLabel[entry.outcome]()} · {seconds(entry.duration_ms / 1000)}
											</dd>
											{#if entry.confidence !== null}
												<dt class="text-muted-foreground">{m.log_confidence()}</dt>
												<dd>
													{formatNumber(entry.confidence, {
														style: 'percent',
														maximumFractionDigits: 0
													})}
												</dd>
											{/if}
											{#if entry.reason}
												<dt class="text-muted-foreground">{m.log_reason()}</dt>
												<dd class="break-words">{entry.reason}</dd>
											{/if}
										</dl>
									</div>
								{/each}
							</details>
						{/if}
					{/each}
				</li>
			{/each}
		</ol>
	</section>

	<aside
		aria-labelledby="run-heading"
		class="flex min-w-0 flex-[1_1_18rem] flex-col gap-4 rounded-2xl border bg-card p-5 lg:max-w-sm"
	>
		<h2 id="run-heading" class="font-semibold">{m.log_run({ run: document.processing.run })}</h2>
		<dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
			<dt class="text-muted-foreground">{m.log_status()}</dt>
			<dd>{statusLabel[document.processing.status]()}</dd>
			{#if started}
				<dt class="text-muted-foreground">{m.log_started()}</dt>
				<dd>{formatDate(started, { dateStyle: 'medium', timeStyle: 'medium' })}</dd>
			{/if}
			{#if started && finished && document.processing.status !== 'processing'}
				<dt class="text-muted-foreground">{m.log_duration()}</dt>
				<dd>{seconds((new Date(finished).getTime() - new Date(started).getTime()) / 1000)}</dd>
			{/if}
			{#if tokens}
				<dt class="text-muted-foreground">{m.log_tokens()}</dt>
				<dd>
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
	</aside>
</div>

{#if prompt}
	<PromptDialog
		bind:open={promptOpen}
		title={prompt.title}
		meta={prompt.meta}
		calls={prompt.calls}
	/>
{/if}
