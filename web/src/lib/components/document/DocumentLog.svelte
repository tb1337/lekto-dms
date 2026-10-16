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
	import SignalSummary from '#lib/components/document/SignalSummary.svelte';
	import TokenInfo from '#lib/components/document/TokenInfo.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
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
	import {
		nodeRun,
		pastStatus,
		runNumbers,
		runSpan,
		runTokens,
		startedAgain,
		stateOf,
		type NodeRun
	} from '#lib/runs.ts';
	import { usageOf } from '#lib/usage.ts';
	import { cn } from '#lib/utils.ts';

	type Document = components['schemas']['DocumentDetails'];
	type LogEntry = components['schemas']['LogEntry'];
	type Exchange = components['schemas']['RunExchangeOut'];
	type ExchangeNode = components['schemas']['ExchangeNode'];
	type Outcome = components['schemas']['Outcome'];

	// The processing of a document in one run, the current one or one chosen beside it: every
	// node of the graph in a row by level (nodes that run side by side share one), with its
	// state and duration, live with the events in the current run; below each what it did in
	// that run (owner and admins), with the model's token figures and prompt. A node the run did
	// not start again shows what it did in the earlier run the run worked with.
	let {
		document,
		graph,
		manageable,
		lookup = null,
		onreprocess
	}: {
		document: Document;
		graph: readonly GraphNode[];
		manageable: boolean;
		/** Names of contacts and types in what the signals said. */
		lookup?: Lookup | null;
		onreprocess: () => void;
	} = $props();

	// The nodes that ask a language model and keep what they sent: OCR when the vision model
	// read the pages.
	const MODEL_NODES: readonly ExchangeNode[] = ['ocr', 'signal_llm', 'fields'];

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

	// The run shown: the current one, unless the viewer chose another while it was current (a
	// new run, or another document, shows its current run).
	const currentRun = $derived(document.processing.run);
	let chosen = $state<{ id: string; current: number; run: number } | null>(null);
	const shownRun = $derived(
		chosen !== null && chosen.id === document.id && chosen.current === currentRun
			? chosen.run
			: currentRun
	);
	const isCurrent = $derived(shownRun === currentRun);
	const runs = $derived(runNumbers(entries ?? [], currentRun));
	const again = $derived(startedAgain(entries ?? [], graph, shownRun));

	function choose(run: number) {
		chosen = { id: document.id, current: currentRun, run };
	}

	// What a node did in the run shown, and its state: live in the current run (a node waiting
	// or running there has nothing to keep), by its last entry in a past one (null: it did not
	// run).
	function nodeView(node: Node): { done: NodeRun; state: NodeState | null } {
		const log = entries ?? [];
		if (isCurrent) {
			const state = states.get(node) ?? null;
			return { done: nodeRun(log, node, shownRun, state?.status !== 'done'), state };
		}
		const done = nodeRun(log, node, shownRun, again.has(node));
		return { done, state: stateOf(node, done.entries) };
	}

	const outcomeLabel: Record<Outcome, () => string> = {
		ok: m.outcome_ok,
		uncertain: m.outcome_uncertain,
		failed: m.outcome_failed
	};

	function look(state: NodeState | null) {
		if (state === null) return { icon: Circle, label: m.log_not_run(), tone: 'muted', spin: false };
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

	function duration(state: NodeState | null): string | null {
		if (state === null) return null;
		const value = durationSeconds(state, now);
		return value === null ? null : seconds(value, value < 10 ? 1 : 0);
	}

	const time = (value: string) => formatDate(value, { timeStyle: 'medium' });

	// The nodes that work with the language model's answer when they do not ask it themselves:
	// the judge always, the fields for the fields the model was asked about.
	const ANSWERED: readonly Node[] = ['judge', 'fields'];
	// Entries that are no model's work: a person's, a takeover's.
	const NOT_THE_MODEL = new Set(['person', 'imported']);

	type Asked = { node: ExchangeNode; exchange: Exchange };

	/** What the language model was asked for an entry: its own node's call in its run, or the
	 * model's call it worked with (the latest of `signal_llm` up to its run). */
	function exchangeOf(entry: LogEntry): Asked | undefined {
		const own = (MODEL_NODES as readonly Node[]).includes(entry.node)
			? exchanges[entry.node]?.find((exchange) => exchange.run === entry.run)
			: undefined;
		if (own) return { node: entry.node as ExchangeNode, exchange: own };
		if (!ANSWERED.includes(entry.node) || !entry.model_version) return undefined;
		if (NOT_THE_MODEL.has(entry.model_version)) return undefined;
		const answer = (exchanges.signal_llm ?? [])
			.filter((exchange) => exchange.run <= entry.run)
			.reduce<Exchange | undefined>(
				(latest, exchange) => (latest && latest.run > exchange.run ? latest : exchange),
				undefined
			);
		return answer ? { node: 'signal_llm', exchange: answer } : undefined;
	}

	function showPrompt(entry: LogEntry, asked: Asked) {
		prompt = {
			title: m.prompt_title({ node: NODE_LABELS[asked.node]() }),
			meta: [entry.model_version, time(entry.started_at), m.log_run({ run: asked.exchange.run })]
				.filter(Boolean)
				.join(' · '),
			calls: asked.exchange.calls
		};
		promptOpen = true;
	}

	// A run at a glance: how it stands or ended, when it began, when it ended (not while it
	// runs), by its entries; without the log, the current run by the states of its nodes.
	type Status = Document['processing']['status'];
	function about(run: number): { status: Status; started: string | null; finished: string | null } {
		const current = run === currentRun;
		const status = current ? document.processing.status : pastStatus(entries ?? [], graph, run);
		let started: string | null;
		let finished: string | null;
		if (entries === null) {
			const times = (pick: (state: NodeState) => string | null) =>
				document.processing.nodes
					.map(pick)
					.filter((value): value is string => value !== null)
					.sort();
			started = times((state) => state.started_at)[0] ?? null;
			finished = times((state) => state.finished_at).at(-1) ?? null;
		} else {
			const span = runSpan(entries, run);
			const running = current
				? document.processing.nodes
						.filter((state) => state.status === 'running')
						.map((state) => state.started_at)
				: [];
			started =
				[span?.started, ...running]
					.filter((value): value is string => typeof value === 'string')
					.sort()[0] ?? null;
			finished = span?.finished ?? null;
		}
		return { status, started, finished: status === 'processing' ? null : finished };
	}
	const shown = $derived(about(shownRun));
	const tokens = $derived(runTokens(entries ?? [], shownRun));
	const statusLabel: Record<Status, () => string> = {
		processing: m.lane_running,
		review: m.lane_yellow,
		failed: m.outcome_failed,
		completed: m.lane_green
	};
	const statusTone: Record<Status, string> = {
		processing: 'running',
		review: 'yellow',
		failed: 'red',
		completed: 'green'
	};
	const span = (value: { started: string | null; finished: string | null }) =>
		value.started && value.finished
			? seconds((new Date(value.finished).getTime() - new Date(value.started).getTime()) / 1000)
			: null;
	const canReprocess = $derived(
		manageable &&
			document.processing.status !== 'processing' &&
			reprocessable(graph, document.processing).some((node) => node !== 'receive')
	);
</script>

<!-- The run box beside the nodes where there is room, above them where not; where the view fills
	the window, each scrolls on its own. -->
<div class="@container lg:h-full lg:min-h-0">
	<div
		class="grid items-start gap-6 @4xl:h-full @4xl:grid-cols-[minmax(0,1fr)_20rem] @4xl:grid-rows-[minmax(0,1fr)]"
	>
		<aside
			aria-labelledby="run-heading"
			class="flex min-w-0 flex-col gap-4 rounded-2xl border bg-card p-5 @4xl:order-last @4xl:max-h-full @4xl:overflow-y-auto"
		>
			{#if runs.length > 1}
				<h2 id="run-heading" class="font-semibold">{m.log_runs()}</h2>
				<ul class="-mx-2 -mt-2 flex max-h-80 flex-col gap-0.5 overflow-y-auto">
					{#each runs as run (run)}
						{@const glance = run === shownRun ? shown : about(run)}
						{@const length = span(glance)}
						<li>
							<button
								type="button"
								aria-pressed={run === shownRun}
								onclick={() => choose(run)}
								class={cn(
									'flex w-full flex-col rounded-lg px-2 py-1.5 text-left text-sm transition-colors',
									run === shownRun ? 'bg-secondary' : 'hover:bg-secondary/60'
								)}
							>
								<span class="flex flex-wrap items-baseline gap-x-2">
									<span class="font-medium">{m.log_run({ run })}</span>
									<span class={texts[statusTone[glance.status]]}>
										{statusLabel[glance.status]()}
									</span>
								</span>
								{#if glance.started}
									<span class="text-muted-foreground tabular-nums">
										{[
											formatDate(glance.started, { dateStyle: 'short', timeStyle: 'short' }),
											length
										]
											.filter(Boolean)
											.join(' · ')}
									</span>
								{/if}
							</button>
						</li>
					{/each}
				</ul>
			{:else}
				<h2 id="run-heading" class="font-semibold">{m.log_run({ run: shownRun })}</h2>
			{/if}
			<dl
				class={cn(
					'grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm',
					runs.length > 1 && 'border-t border-muted pt-4'
				)}
			>
				<dt class="text-muted-foreground">{m.log_status()}</dt>
				<dd>{statusLabel[shown.status]()}</dd>
				{#if shown.started}
					<dt class="text-muted-foreground">{m.log_started()}</dt>
					<dd>{formatDate(shown.started, { dateStyle: 'medium', timeStyle: 'medium' })}</dd>
				{/if}
				{#if span(shown)}
					<dt class="text-muted-foreground">{m.log_duration()}</dt>
					<dd>{span(shown)}</dd>
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

		<section
			aria-labelledby="log-heading"
			class="flex min-w-0 flex-col gap-2.5 @4xl:h-full @4xl:overflow-y-auto"
		>
			<h2
				id="log-heading"
				class="text-xs font-semibold tracking-wider text-muted-foreground uppercase"
			>
				{m.graph_title()} · {m.log_run({ run: shownRun })}
			</h2>
			{#if problem}<p class="text-destructive" role="alert">{problem}</p>{/if}
			<ol class="flex flex-col gap-2.5">
				{#each rows as row, rowIndex (rowIndex)}
					<li class="flex flex-wrap gap-2.5">
						{#each row as node (node)}
							{@const view = nodeView(node)}
							{#if view.state || !isCurrent}
								{@const state = view.state}
								{@const looks = look(state)}
								<details
									open={state?.outcome === 'uncertain' || state?.outcome === 'failed'}
									data-node={node}
									data-status={state?.status ?? 'not_run'}
									class={cn(
										'group @container min-w-60 flex-1 rounded-2xl border px-4 py-3',
										cards[looks.tone]
									)}
								>
									<!-- Where the card is narrow, the state goes below the name; the icon, the duration and
								     the chevron stay with the first line. -->
									<summary
										class="flex cursor-pointer list-none items-start gap-2.5 [&::-webkit-details-marker]:hidden"
									>
										<span class="flex h-6 shrink-0 items-center">
											<looks.icon
												class={cn('size-4.5', texts[looks.tone], looks.spin && 'animate-spin')}
												aria-hidden="true"
												strokeWidth={2.2}
											/>
										</span>
										<span class="flex min-w-0 flex-wrap items-baseline gap-x-2.5">
											<span class="font-semibold">{NODE_LABELS[node]()}</span>
											<span class="text-sm whitespace-nowrap">
												<span class={texts[looks.tone]}>{looks.label}</span>
												{#if view.done.from !== null}
													<span class="text-muted-foreground">
														· {m.log_from_run({ run: view.done.from })}
													</span>
												{/if}
											</span>
										</span>
										<span
											class="ml-auto text-sm leading-6 whitespace-nowrap text-muted-foreground tabular-nums"
										>
											{duration(state) ?? ''}
										</span>
										<span class="flex h-6 shrink-0 items-center">
											<ChevronDown
												class="size-4 text-muted-foreground transition-transform group-open:rotate-180"
												aria-hidden="true"
											/>
										</span>
									</summary>
									{#if !manageable}
										<p class="mt-2 ml-7 text-sm text-muted-foreground">{m.log_owner_only()}</p>
									{:else if view.done.entries.length === 0 && isCurrent}
										<p class="mt-2 ml-7 text-sm text-muted-foreground">
											{entries === null ? m.loading() : m.log_none()}
										</p>
									{/if}
									{#each view.done.entries as entry, index (`${entry.run}-${index}`)}
										{@const usage = usageOf(entry.output)}
										{@const exchange = exchangeOf(entry)}
										<div class="mt-2.5 ml-7 flex flex-col gap-1.5 text-sm" data-run={entry.run}>
											<div
												class="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground"
											>
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
														id="tokens-{entry.node}-{entry.run}-{index}"
														pages={entry.node === 'ocr'}
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
											<!-- Side by side where the card is wide; a label above its value in a narrow one. -->
											<dl
												class="grid grid-cols-1 gap-x-3 gap-y-0.5 @sm:grid-cols-[auto_minmax(0,1fr)]"
											>
												<dt class="text-muted-foreground">{m.log_outcome()}</dt>
												<dd>
													{outcomeLabel[entry.outcome]()} · {seconds(entry.duration_ms / 1000)}
												</dd>

												{#if entry.reason}
													<dt class="text-muted-foreground">{m.log_reason()}</dt>
													<dd class="wrap-break-word">{entry.reason}</dd>
												{/if}
												<SignalSummary {entry} {lookup} />
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
	</div>
</div>

{#if prompt}
	<PromptDialog
		bind:open={promptOpen}
		title={prompt.title}
		meta={prompt.meta}
		calls={prompt.calls}
	/>
{/if}
