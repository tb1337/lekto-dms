<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { bandOf } from '#lib/band.ts';
	import ProcessingBand from '#lib/components/document/ProcessingBand.svelte';
	import ProcessingGraph from '#lib/components/document/ProcessingGraph.svelte';
	import ProcessingRuns from '#lib/components/document/ProcessingRuns.svelte';
	import ProcessingSummary from '#lib/components/document/ProcessingSummary.svelte';
	import ProcessingTimeline from '#lib/components/document/ProcessingTimeline.svelte';
	import PromptDialog from '#lib/components/document/PromptDialog.svelte';
	import StepEntries from '#lib/components/document/StepEntries.svelte';
	import { desktop } from '#lib/desktop.svelte.ts';
	import { stepHref, stepOf, viewHref, viewOf } from '#lib/document-view.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatDate } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { durationSeconds, reprocessable, type GraphNode, type Node } from '#lib/pipeline.ts';
	import { changesOf, headlineOf } from '#lib/run-summary.ts';
	import { glance, runNumbers, runTokens, startedAgain } from '#lib/runs.ts';
	import { session } from '#lib/session.svelte.ts';
	import { list, object } from '#lib/signals.ts';
	import { byPerson, stepSummary } from '#lib/step-summary.ts';
	import { countsOf, phaseSeconds, phasesOf, stepsOf, stuck, type Step } from '#lib/steps.ts';

	type Document = components['schemas']['DocumentDetails'];
	type LogEntry = components['schemas']['LogEntry'];
	type Exchange = components['schemas']['RunExchangeOut'];
	type ExchangeNode = components['schemas']['ExchangeNode'];

	// The processing of a document (mock D, Tobi 23.10.2026): how the run went at a glance (one
	// sentence, the band, the counts, what changed), its steps in four phases as the cards of the
	// log before, each opening what it did (when, with which model, the tokens and the prompt,
	// why, what it said). The runs stand in their box as before. Live with the events in the
	// current run. On a desktop the view fills the window and only
	// its columns scroll; narrower, everything stands one below the other and the steps run down
	// a line. A step the run did not start again shows what it did in the earlier run the run
	// worked with. Only editors read the log.
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
		/** Names of contacts, types, spaces and users in what the steps said. */
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
	const nodes = $derived(
		graph.length > 0
			? graph.map((entry) => entry.node)
			: document.processing.nodes.map((state) => state.node)
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

	const glanceOf = (run: number) => glance(entries, graph, document.processing, run);
	const shown = $derived(glanceOf(shownRun));
	const steps = $derived(
		stepsOf(nodes, entries ?? [], states, {
			number: shownRun,
			current: isCurrent,
			again,
			status: shown.status
		})
	);
	const groups = $derived(phasesOf(steps));
	const viewer = $derived({ id: session.user?.id, admin: session.isAdmin });
	// Only the current run's open steps still wait for a person.
	const waiting = $derived(isCurrent && shown.status === 'review');

	const headline = $derived(
		headlineOf(
			{ number: shownRun, current: isCurrent, status: shown.status },
			steps,
			document.space_id,
			lookup,
			viewer
		)
	);
	const counts = $derived(countsOf(steps));
	const changes = $derived(
		manageable && entries !== null ? changesOf(entries, graph, shownRun, runs, lookup) : null
	);
	const bandPhases = $derived(bandOf(steps, graph, now));
	const verdict = $derived(steps.find((step) => step.node === 'judge')?.done.entries.at(-1));

	const carriedLabel = $derived(
		counts.carriedFrom === null
			? m.run_count_carried_earlier()
			: m.log_from_run({ run: counts.carriedFrom })
	);

	// The step whose details are open: the one the link names; else, in the current run when it
	// stopped for a person, the step that keeps it (as the log opened what was uncertain or
	// failed), until the viewer closes it.
	const wide = $derived(desktop.current);
	const named = $derived(stepOf(page.url, nodes) as Node | null);
	let closed = $state<{ document: string; run: number } | null>(null);
	const selected = $derived.by(() => {
		if (named !== null) return named;
		if (closed?.document === document.id && closed.run === shownRun) return null;
		const stopped = isCurrent && (shown.status === 'review' || shown.status === 'failed');
		return stopped ? (stuck(steps)[0]?.node ?? null) : null;
	});

	async function toggle(node: Node) {
		if (selected === node) {
			closed = { document: document.id, run: shownRun };
			await goto(stepHref(page.url, null), { replace: true, reset: false });
			return;
		}
		await goto(stepHref(page.url, node), { replace: true, reset: false });
		// The details open below the steps (on a desktop) or below the card: into view.
		await tick();
		window.document
			.getElementById(wide ? 'step-details' : `step-details-${node}`)
			?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
	}

	const tokens = $derived(runTokens(entries ?? [], shownRun));
	const canReprocess = $derived(
		manageable &&
			document.processing.status !== 'processing' &&
			reprocessable(graph, document.processing).some((node) => node !== 'receive')
	);

	function durationOf(entry: Step): string | null {
		if (entry.state === null) return null;
		const value = durationSeconds(entry.state, now);
		return value === null ? null : formatDuration(value);
	}

	function summaryOf(entry: Step): string | null {
		if (!manageable || entries === null) return null;
		return stepSummary(
			entry.node,
			entry.state,
			entry.done.entries.at(-1),
			waiting ? 'review' : 'completed',
			lookup
		);
	}

	function phaseDuration(phase: readonly Step[]): string | null {
		if (entries === null && !isCurrent) return null;
		const value = phaseSeconds(phase, now);
		return value === null ? null : formatDuration(value);
	}

	const phaseDurationOf = (phase: string) =>
		phaseDuration(groups.find((group) => group.phase === phase)?.steps ?? []);

	// The nodes that work with the language model's answer when they do not ask it themselves:
	// the judge always, the fields for the fields the model was asked about.
	const ANSWERED: readonly Node[] = ['judge', 'fields'];

	type Asked = { node: ExchangeNode; exchange: Exchange };

	/** What the language model was asked for an entry: its own node's call in its run, or the
	 * model's call it worked with (the latest of `signal_llm` up to its run). */
	function exchangeOf(entry: LogEntry): Asked | undefined {
		const own = (MODEL_NODES as readonly Node[]).includes(entry.node)
			? exchanges[entry.node]?.find((exchange) => exchange.run === entry.run)
			: undefined;
		if (own) return { node: entry.node as ExchangeNode, exchange: own };
		if (!ANSWERED.includes(entry.node) || !entry.model_version || byPerson(entry)) {
			return undefined;
		}
		const answer = (exchanges.signal_llm ?? [])
			.filter((exchange) => exchange.run <= entry.run)
			.reduce<Exchange | undefined>(
				(found, exchange) => (found && found.run > exchange.run ? found : exchange),
				undefined
			);
		return answer ? { node: 'signal_llm', exchange: answer } : undefined;
	}

	function showPrompt(entry: LogEntry) {
		const asked = exchangeOf(entry);
		if (!asked) return;
		prompt = {
			title: m.prompt_title({ node: NODE_LABELS[asked.node]() }),
			meta: [
				entry.model_version,
				formatDate(entry.started_at, { timeStyle: 'medium' }),
				m.log_run({ run: asked.exchange.run })
			]
				.filter(Boolean)
				.join(' · '),
			calls: asked.exchange.calls
		};
		promptOpen = true;
	}

	// The document tab with the form: the filing question and the review are there.
	const reviewHref = $derived(viewHref(page.url, { left: viewOf(page.url).left, right: 'form' }));
	// The way to the filing question from the verdict, while its space waits for a person.
	const filingHref = $derived.by(() => {
		if (!waiting) return null;
		const open = list(object(verdict?.output).fields)
			.map(object)
			.some((check) => check.field === 'space' && check.outcome === 'uncertain');
		return open ? reviewHref : null;
	});
</script>

{#snippet details(step: Step)}
	<StepEntries
		{step}
		{manageable}
		loading={entries === null}
		current={isCurrent}
		{lookup}
		{filingHref}
		hasPrompt={(entry) => exchangeOf(entry) !== undefined}
		onprompt={showPrompt}
	/>
{/snippet}

{#snippet summary()}
	<ProcessingSummary {headline} {counts} {changes} {reviewHref} {canReprocess} {onreprocess}>
		{#snippet band()}
			<ProcessingBand
				phases={bandPhases}
				run={shownRun}
				{wide}
				phaseDuration={phaseDurationOf}
				{carriedLabel}
			/>
		{/snippet}
	</ProcessingSummary>
{/snippet}

{#snippet runBox()}
	<ProcessingRuns
		{runs}
		shown={shownRun}
		{glanceOf}
		{tokens}
		{canReprocess}
		onchoose={choose}
		{onreprocess}
	/>
{/snippet}

<!-- On a desktop the view fills the window: the left column and the box of the runs scroll
     each on their own, the page does not. Both are positioned, so what lies absolutely in them
     (text for screen readers) scrolls with them instead of stretching the page. -->
<div class="lg:h-full lg:min-h-0">
	{#if problem}<p class="mb-4 text-destructive" role="alert">{problem}</p>{/if}
	{#if wide}
		<div
			class="grid h-full grid-cols-[minmax(0,1fr)_20rem] grid-rows-[minmax(0,1fr)] items-start gap-6"
		>
			<div class="relative flex max-h-full min-h-0 min-w-0 flex-col gap-4 overflow-y-auto pr-1">
				{@render summary()}
				<ProcessingGraph
					{groups}
					run={shownRun}
					{selected}
					{summaryOf}
					{durationOf}
					{phaseDuration}
					ontoggle={toggle}
					{details}
				/>
			</div>
			<div class="relative max-h-full min-w-0 overflow-y-auto">
				{@render runBox()}
			</div>
		</div>
	{:else}
		<div class="flex flex-col gap-4">
			{@render summary()}
			{@render runBox()}
			<ProcessingTimeline
				{groups}
				run={shownRun}
				{selected}
				{summaryOf}
				{durationOf}
				{phaseDuration}
				ontoggle={toggle}
				{details}
			/>
		</div>
	{/if}
</div>

{#if prompt}
	<PromptDialog
		bind:open={promptOpen}
		title={prompt.title}
		meta={prompt.meta}
		calls={prompt.calls}
	/>
{/if}
