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
	import SignalMatrix from '#lib/components/document/SignalMatrix.svelte';
	import type { DetailContext } from '#lib/components/document/StepDetails.svelte';
	import StepEntries from '#lib/components/document/StepEntries.svelte';
	import { desktop } from '#lib/desktop.svelte.ts';
	import { pageHref, stepHref, stepOf, viewHref, viewOf } from '#lib/document-view.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { describeError } from '#lib/errors.ts';
	import { coalesced } from '#lib/coalesce.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatDate } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { durationSeconds, reprocessable, type GraphNode, type Node } from '#lib/pipeline.ts';
	import { changesOf, headlineOf } from '#lib/run-summary.ts';
	import { glance, runNumbers, runTokens, startedAgain } from '#lib/runs.ts';
	import { session } from '#lib/session.svelte.ts';
	import { decidedBy, matrixOf, verdictOf } from '#lib/signal-matrix.ts';
	import { list, object } from '#lib/signals.ts';
	import { classifierThresholds } from '#lib/step-details.ts';
	import { byPerson, stepSummary } from '#lib/step-summary.ts';
	import { countsOf, phaseSeconds, phasesOf, stepsOf, stuck, type Step } from '#lib/steps.ts';

	type Document = components['schemas']['DocumentDetails'];
	type LogEntry = components['schemas']['LogEntry'];
	type Exchange = components['schemas']['RunExchangeOut'];
	type ExchangeNode = components['schemas']['ExchangeNode'];
	type Files = components['schemas']['DocumentFilesOut'];
	type Reading = components['schemas']['ReadingOut'];

	// The processing of a document (mock D, Tobi 23.10.2026): how the run went at a glance (one
	// sentence, the band, the counts, what changed), its steps in four phases as the cards of the
	// log before, each opening what it did (when, with which model, the tokens and the prompt,
	// why, what it said), and which signal named what. The runs stand in their box as before.
	// Live with the events in the current run. On a desktop the view fills the window and only
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
	// The document's files and how its text was read, for the details of the text recognition;
	// without them the details leave that out.
	let files = $state<Files | null>(null);
	let reading = $state<Reading | null>(null);
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
			void loadExtras(wanted, request);
		} catch (error) {
			if (wanted === document.id && request === latest) problem = describeError(error);
		}
	}

	/** The files and the reading, beside the log; a failure leaves them out, not the log. */
	async function loadExtras(wanted: string, request: number) {
		const [found, read] = await Promise.all([
			unwrap(api.GET('/api/v1/documents/{id}/files', { params: { path: { id: wanted } } })).catch(
				() => null
			),
			unwrap(api.GET('/api/v1/documents/{id}/reading', { params: { path: { id: wanted } } })).catch(
				() => null
			)
		]);
		if (wanted !== document.id || request !== latest) return;
		files = found && typeof found === 'object' && 'original' in found ? found : null;
		reading = read && typeof read === 'object' && Array.isArray(read.pages) ? read : null;
	}

	// Loaded once per document and after completed nodes; a new state of the document (every
	// event) does not load it again.
	const documentId = $derived(document.id);
	let loadedFor = '';
	$effect(() => {
		const id = documentId;
		void events.generation;
		untrack(() => {
			if (loadedFor !== id) {
				entries = null;
				files = null;
				reading = null;
				problem = null;
				loadedFor = id;
			}
			void load();
		});
		// Nodes side by side complete together: loaded once after them.
		const reload = coalesced(() => void load());
		const stop = events.subscribe((event) => {
			if (event.document_id === id && event.type === 'document.node_completed') reload();
		});
		return () => {
			stop();
			reload.cancel();
		};
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

	const glanceOf = (run: number) =>
		glance(entries, graph, document.processing, run, document.first_lane);
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
	// Whether the steps the shown run kept from an earlier one are known: by the log (a reader
	// never loads it, an editor until it is there), or in the first run, which kept none.
	// Otherwise their times would count as this run's: no times then.
	const timed = $derived(entries !== null || shownRun === 1);
	const changes = $derived(
		manageable && entries !== null ? changesOf(entries, graph, shownRun, runs, lookup) : null
	);
	const bandPhases = $derived(bandOf(steps, graph, now, timed));
	// The verdict the shown run worked with: the judge's own entry in it, or the one it kept;
	// after a person's confirmation (their entry for the judge, without checks) the latest
	// verdict before. None while the judge is still to run again.
	const judged = $derived(steps.find((step) => step.node === 'judge')?.done.entries ?? []);
	const verdict = $derived(
		judged.filter((entry) => !byPerson(entry)).at(-1) ??
			(judged.some(byPerson) ? verdictOf(entries ?? [], shownRun) : undefined)
	);
	// What a person decided with their confirmation in the current run, by what the document
	// holds now; in a past run the matrix shows the verdict as it ended.
	const decided = $derived(
		isCurrent
			? decidedBy(
					judged.findLast((entry) => entry.model_version === 'person'),
					{
						contact: document.contact_id,
						document_type: document.document_type_id,
						topic: document.topic_id,
						space: document.space_id
					}
				)
			: new Map<string, unknown>()
	);
	const matrix = $derived(
		manageable && entries !== null
			? matrixOf(verdict, waiting, document.space_id, lookup, viewer, decided)
			: []
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

	// The step pointed at or focused, in the band or at its card: both light it up.
	let highlighted = $state<Node | null>(null);
	const highlight = (node: Node | null) => (highlighted = node);

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
		if (!timed) return null;
		const value = phaseSeconds(phase, now);
		return value === null ? null : formatDuration(value);
	}

	/** How a step of the shown run that did not end OK by itself came to count as OK. */
	function noteOf(node: Node): string | null {
		const step = steps.find((entry) => entry.node === node);
		return step?.overruled ? summaryOf(step) : null;
	}

	const phaseDurationOf = (phase: string) =>
		phaseDuration(groups.find((group) => group.phase === phase)?.steps ?? []);

	const time = (value: string) => formatDate(value, { timeStyle: 'medium' });

	/** The band's reading line for a step: when it ran (in its own run, for a step kept from an
	 * earlier one) and what it did. */
	function readingOf(node: Node): string | null {
		const step = steps.find((entry) => entry.node === node);
		if (!step) return null;
		const entry = step.done.entries.at(-1);
		const started = entry?.started_at ?? step.state?.started_at ?? null;
		const finished = entry
			? new Date(new Date(entry.started_at).getTime() + entry.duration_ms).toISOString()
			: (step.state?.finished_at ?? null);
		const when = started
			? finished
				? `${time(started)} → ${time(finished)}`
				: `${time(started)} →`
			: null;
		return [when, summaryOf(step)].filter(Boolean).join(' · ') || null;
	}

	// The reading line while no step is lit: how to light one (with a pointer), and the run's span.
	const idle = $derived.by(() => {
		const span = shown.started
			? shown.finished
				? m.run_band_span({ run: shownRun, start: time(shown.started), end: time(shown.finished) })
				: m.run_band_since({ run: shownRun, start: time(shown.started) })
			: null;
		return [wide ? m.run_band_hint() : null, span].filter(Boolean).join(' · ') || null;
	});

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

	// What the drawn details need: the latest run of each step (the files, the reading and the
	// text are the document's current ones), the classifier's thresholds as the verdict tells
	// them, the ways to the text and to a page.
	const detailContext: DetailContext = $derived({
		documentId: document.id,
		latest: Object.fromEntries(
			nodes.map((node) => [
				node,
				Math.max(0, ...(entries ?? []).filter((entry) => entry.node === node).map((e) => e.run))
			])
		),
		files,
		poor: (reading?.pages ?? []).filter((each) => each.poor).map((each) => each.page),
		thresholds: classifierThresholds(verdict),
		textHref: viewHref(page.url, { left: 'text', right: viewOf(page.url).right }),
		pageHref: (number: number) => pageHref(page.url, number)
	});

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
		context={detailContext}
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
				{noteOf}
				reading={readingOf}
				{idle}
				{highlighted}
				expanded={selected}
				onhighlight={highlight}
				onselect={toggle}
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
<div class="lg:flex lg:h-full lg:min-h-0 lg:flex-col">
	{#if problem}<p class="mb-4 shrink-0 text-destructive" role="alert">{problem}</p>{/if}
	{#if wide}
		<div
			class="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_20rem] grid-rows-[minmax(0,1fr)] items-start gap-6"
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
					{highlighted}
					onhighlight={highlight}
					ontoggle={toggle}
					{details}
				/>
				{#if matrix.length > 0}<SignalMatrix rows={matrix} chips={false} />{/if}
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
				{highlighted}
				onhighlight={highlight}
				ontoggle={toggle}
				{details}
			/>
			{#if matrix.length > 0}<SignalMatrix rows={matrix} chips={true} />{/if}
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
