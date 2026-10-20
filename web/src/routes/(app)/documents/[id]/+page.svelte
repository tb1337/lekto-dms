<script lang="ts">
	import File from '@lucide/svelte/icons/file';
	import ListChecks from '@lucide/svelte/icons/list-checks';
	import SquarePen from '@lucide/svelte/icons/square-pen';
	import TextAlignStart from '@lucide/svelte/icons/text-align-start';
	import { onMount, tick, untrack, type Snippet } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import DocumentFacts from '#lib/components/document/DocumentFacts.svelte';
	import DocumentFiles from '#lib/components/document/DocumentFiles.svelte';
	import DocumentForm from '#lib/components/document/DocumentForm.svelte';
	import DocumentLog from '#lib/components/document/DocumentLog.svelte';
	import DocumentHeader from '#lib/components/document/DocumentHeader.svelte';
	import DocumentText from '#lib/components/document/DocumentText.svelte';
	import PageImages from '#lib/components/document/PageImages.svelte';
	import PdfViewer from '#lib/components/PdfViewer.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import TabBar from '#lib/components/TabBar.svelte';
	import * as Alert from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import {
		inboxDocument,
		keepPlace,
		neighbours,
		nextDecision,
		type InboxPlace,
		LEFT,
		type Left,
		PRESETS,
		presetOf,
		presetView,
		type Preset,
		rememberedView,
		rememberView,
		type Right,
		tabHref,
		tabOf,
		type Mark,
		type Place,
		type Review,
		type Tab,
		type View,
		viewerSources,
		viewHref,
		viewOf
	} from '#lib/document-view.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import { events, NODE_EVENTS } from '#lib/events.svelte.ts';
	import { inbox as inboxSummary } from '#lib/inbox.svelte.ts';
	import { loadLookup, type Lookup } from '#lib/masterdata.svelte.ts';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import { canEdit, canManage } from '#lib/permissions.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { scope } from '#lib/scope.svelte.ts';
	import { hasText, type GraphNode } from '#lib/pipeline.ts';
	import { phone } from '#lib/phone.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import {
		factCounts,
		spanMarks,
		type CodeFacts,
		type CodePlace,
		type Facts,
		type Span
	} from '#lib/facts.ts';
	import { adviceText, visionAvailable, type Reading, type Vision } from '#lib/vision.ts';

	type Document = components['schemas']['DocumentDetails'];

	// One view for every document, from the inbox and from the list: the document (on the left
	// its pages or its text, on the right its details or its facts), its files (metadata) and
	// the processing (log). The view of the document tab is in the link; without one, the
	// browser's last.
	const id = $derived(page.params.id ?? '');
	const tab = $derived(tabOf(page.url));
	const view = $derived(viewOf(page.url, rememberedView()));
	const fromInbox = $derived(page.url.searchParams.get('from') === 'inbox');
	let document = $state<Document | null>(null);
	let review = $state<Review | null>(null);
	let lookup = $state<Lookup | null>(null);
	let graph = $state<GraphNode[]>([]);
	let vision = $state<Vision | null>(null);
	let reading = $state<Reading | null>(null);
	let facts = $state<Facts | null>(null);
	// A code shown on its page from the content (`Auf der Seite zeigen`).
	let codeMarks = $state<Mark[]>([]);
	// The open documents of the inbox, in its order, opened from there.
	let inboxPlaces = $state<InboxPlace[] | null>(null);
	let inboxReady: Promise<void> = Promise.resolve();
	let problem = $state<unknown>(null);
	// Each pane on the right marks what it holds in the one on the left: the form its fields'
	// quotes, on the pages (`marks`) and in the text (`fieldQuotes`); the facts where they
	// stand, on the pages (`factMarks`) and in the text (`textMarks`).
	let marks = $state<Mark[]>([]);
	let fieldQuotes = $state<string[]>([]);
	let factMarks = $state<Mark[]>([]);
	let textMarks = $state<Span[]>([]);
	// On a phone one pane at a time: the left one or the right one, chosen in the bar of four.
	let side = $state<'left' | 'right'>('left');
	let viewer = $state<PdfViewer | null>(null);
	let textPane = $state<DocumentText | null>(null);
	let header = $state<DocumentHeader | null>(null);

	const user = $derived(session.user);
	const editable = $derived(document !== null && canEdit(document, user));
	const manageable = $derived(document !== null && canManage(document, user));
	// The archive exists once the text is recognised; until then the page images stand in, or,
	// before they are rendered, the original PDF.
	const archive = $derived(
		document?.processing.nodes.some(
			(state) => state.node === 'ocr' && state.status === 'done' && state.outcome !== 'failed'
		) ?? false
	);
	const inbox = $derived(
		fromInbox && inboxPlaces
			? neighbours(
					inboxPlaces.map((place) => place.id),
					id
				)
			: null
	);
	// After confirming, the next document that waits for a decision; not a new one, nor one in
	// processing.
	const nextUp = $derived(fromInbox && inboxPlaces ? nextDecision(inboxPlaces, id) : null);

	// An answer for a document the page has left behind, or one overtaken by a later request
	// (several events arrive at once), must not replace the current state.
	let latest = 0;
	async function load() {
		const wanted = id;
		const request = ++latest;
		try {
			const loaded = await unwrap(
				api.GET('/api/v1/documents/{id}', { params: { path: { id: wanted } } })
			);
			const params = { params: { path: { id: wanted } } };
			const [reviewed, read] = canManage(loaded, session.user)
				? await Promise.all([
						unwrap(api.GET('/api/v1/documents/{id}/review', params)),
						unwrap(api.GET('/api/v1/documents/{id}/reading', params))
					])
				: [null, null];
			// Not asked for before there is a text (in processing, or failed before it was read).
			const found = hasText(loaded.processing) ? await loadFacts(wanted) : null;
			if (wanted === id && request === latest) {
				document = loaded;
				review = reviewed;
				reading = read;
				facts = found;
				problem = null;
				reportSeen(loaded);
			}
		} catch (error) {
			if (wanted === id && request === latest) problem = error;
		}
	}

	/** The facts of the document; none while it has no text. */
	async function loadFacts(wanted: string): Promise<Facts | null> {
		try {
			return await unwrap(
				api.GET('/api/v1/documents/{id}/facts', { params: { path: { id: wanted } } })
			);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) return null;
			throw error;
		}
	}

	async function reloadFacts() {
		const wanted = id;
		try {
			const found = await loadFacts(wanted);
			if (wanted === id) facts = found;
		} catch (error) {
			reportError(error);
		}
	}

	/** Show a code where it stands: the details on `place`, every place of the code marked. */
	async function showCode(code: CodeFacts, place: CodePlace) {
		codeMarks = code.places.map((each) => ({
			key: `code:${each.page}`,
			label: code.format,
			page: each.page,
			boxes: each.boxes,
			derived: false,
			pinned: each.page === place.page
		}));
		side = 'left';
		await show({ ...view, left: 'pages' });
		// The viewer lays its pages out after it is shown.
		for (const wait of [300, 900, 1800]) setTimeout(() => viewer?.reveal(place), wait);
	}

	async function loadInbox() {
		try {
			const listed = await unwrap(
				api.GET('/api/v1/inbox', {
					params: { query: { limit: 100, all_users: scope.query } }
				})
			);
			const now = listed.items.map((item) => ({ id: item.document.id, tab: item.tab }));
			inboxPlaces = keepPlace(inboxPlaces ?? [], now, id);
		} catch (error) {
			reportError(error);
		}
	}

	// Opening the view counts as seen (a read through the API does not), from anywhere: the
	// inbox, the archive, a search, a link. Seen while the document is processed does not count
	// (it is not new yet), so it is reported again when the open document turns green. Opened
	// from the inbox, after the inbox is known: the document keeps its place there.
	let reported: { id: string; green: boolean } | null = null;
	function reportSeen(loaded: Document) {
		const green = loaded.lane === 'green';
		const report = reported?.id !== loaded.id || (green && !reported.green);
		reported = { id: loaded.id, green };
		if (!report) return;
		void inboxReady
			.then(() => api.PUT('/api/v1/documents/{id}/seen', { params: { path: { id: loaded.id } } }))
			.then(({ response }) => {
				if (response.ok) void inboxSummary.refresh();
			})
			.catch(() => {
				// Seen is bookkeeping; the next opening reports it again.
			});
	}

	$effect(() => {
		void id;
		untrack(() => {
			if (document && document.id !== id) {
				document = null;
				review = null;
				reading = null;
				facts = null;
				marks = [];
				codeMarks = [];
				fieldQuotes = [];
				factMarks = [];
				textMarks = [];
			}
		});
	});

	$effect(() => {
		void id;
		void events.generation;
		void load();
	});

	// Again on every document opened: what changed at the one before (confirmed) came while it
	// was no longer shown.
	$effect(() => {
		void id;
		void events.generation;
		void scope.allUsers;
		if (fromInbox) untrack(() => (inboxReady = loadInbox()));
	});

	// Again after a master data dialog saved here (a contact opened from its facts): names,
	// aliases and identifiers decide what the facts show.
	let savedBefore = masterDataDialogs.changed;
	$effect(() => {
		const saved = masterDataDialogs.changed;
		if (saved === savedBefore) return;
		savedBefore = saved;
		untrack(() => {
			loadLookup().then((value) => (lookup = value), reportError);
			void reloadFacts();
		});
	});

	onMount(() => {
		loadLookup().then((value) => (lookup = value), reportError);
		unwrap(api.GET('/api/v1/pipeline')).then((value) => {
			graph = value.nodes;
			vision = value.vision;
		}, reportError);
		return events.subscribe((event) => {
			if (event.document_id !== id) return;
			if (event.type === 'document.deleted')
				void goto(fromInbox ? `${BASE}/inbox` : `${BASE}/documents`);
			else void load();
			if (fromInbox && !NODE_EVENTS.has(event.type)) void loadInbox();
		});
	});

	/** Show a field's quote where it stands in the pane on the left. */
	function reveal(place: Place) {
		revealLeft(place);
	}

	/** Show what is marked in the pane on the left: in the text, or `place` on the pages (none:
	 * nothing to show there). On a phone the left pane takes the screen first. */
	function revealLeft(place: Place | undefined) {
		if (view.left === 'pages' && !place) return;
		const hidden = phone.current && side !== 'left';
		side = 'left';
		if (view.left === 'text') void tick().then(() => textPane?.revealMark());
		else if (place && !hidden) viewer?.reveal(place);
		// The viewer lays its pages out once it is shown.
		else if (place)
			for (const wait of [300, 900, 1800]) setTimeout(() => viewer?.reveal(place), wait);
	}

	/** A pane's switch for its head; none on a phone, where the bar of four takes its place. */
	function paneSwitch(snippet: Snippet): Snippet | undefined {
		return phone.current ? undefined : snippet;
	}

	/** The pane a phone shows, by what it shows: one of the left's or the right's. */
	function showOnPhone(next: string) {
		if ((LEFT as readonly string[]).includes(next)) {
			side = 'left';
			if (next !== view.left) void show({ ...view, left: next as Left });
		} else {
			side = 'right';
			if (next !== view.right) void show({ ...view, right: next as Right });
		}
	}

	// A pane once shown stays, hidden while the other one is: the form keeps what was typed,
	// the pages their zoom and place.
	const opened = new SvelteSet<Left | Right>();
	$effect(() => {
		if (tab !== 'document') return;
		rememberView(view);
		untrack(() => {
			opened.add(view.left);
			opened.add(view.right);
		});
	});

	/** Show `view` in the document tab; a switch, not a step back in the history. */
	function show(next: View) {
		return goto(viewHref(page.url, next), { replace: true, reset: false });
	}

	/** Mark where a fact stands; after a click, show the first place in the pane on the left. */
	function markFact(spans: Span[], scroll: boolean, label: string) {
		textMarks = spans;
		factMarks = spanMarks(spans, label);
		if (scroll && spans.length > 0) revealLeft(spans.flatMap((span) => span.locations)[0]);
	}

	async function confirmed(next: string | null) {
		// It waits for no decision any more, whatever the next list says.
		const left = id;
		inboxPlaces = inboxPlaces?.filter((place) => place.id !== left) ?? null;
		await goto(next ? inboxDocument(next) : `${BASE}/inbox`);
	}

	const PRESET_NAMES: Record<Preset, { label: () => string; hint: () => string }> = {
		check: { label: m.view_preset_check, hint: m.view_preset_check_hint },
		read: { label: m.view_preset_read, hint: m.view_preset_read_hint },
		locate: { label: m.view_preset_locate, hint: m.view_preset_locate_hint },
		compare: { label: m.view_preset_compare, hint: m.view_preset_compare_hint }
	};
	const presetsId = $props.id();

	const tabs: { tab: Tab; label: () => string }[] = [
		{ tab: 'document', label: m.tab_document },
		{ tab: 'metadata', label: m.tab_metadata },
		{ tab: 'log', label: m.tab_log }
	];
	const attention = $derived(
		document?.processing.nodes.some(
			(state) => state.outcome === 'uncertain' || state.outcome === 'failed'
		) ?? false
	);
	const notFound = $derived(problem instanceof ApiError && problem.status === 404);
	// The text recognition made the document red or yellow: reading it with the vision model is
	// advised, and offered right here.
	const advice = $derived(
		document && manageable && visionAvailable(vision, graph, document.processing)
			? adviceText(reading)
			: null
	);
</script>

<svelte:head><title>{document?.title ?? m.nav_documents()} · {m.app_name()}</title></svelte:head>

<!-- From the desktop width on the view fills the window; only its cards scroll. -->
<div class="flex flex-col gap-4 lg:h-full lg:min-h-0" data-wide>
	{#if problem}
		<div class="flex flex-col items-start gap-3" role="alert">
			<p class="text-destructive">{notFound ? m.document_not_found() : describeError(problem)}</p>
			{#if !notFound}<Button variant="outline" onclick={load}>{m.retry()}</Button>{/if}
		</div>
	{:else if !document}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<DocumentHeader
			bind:this={header}
			{document}
			{lookup}
			{graph}
			{archive}
			{inbox}
			{vision}
			{reading}
			onchanged={load}
		/>

		{#if advice}
			<Alert.Root variant="tip" role="status" class="flex flex-wrap items-center gap-3">
				<Alert.Description class="min-w-0 flex-1">{advice}</Alert.Description>
				<Button size="sm" onclick={() => header?.startVision()}>{m.vision_read()}</Button>
			</Alert.Root>
		{/if}

		<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
			<TabBar
				label={m.tabs_label()}
				tabs={tabs.map((entry) => ({
					key: entry.tab,
					href: tabHref(page.url, entry.tab),
					label: entry.label(),
					marker: entry.tab === 'log' && attention ? m.tab_log_attention() : undefined
				}))}
				current={tab}
			/>
			{#if tab === 'document'}
				<!-- Both panes at once, by what the view is for; on a phone the panes' bar does it. -->
				<div class="ml-auto flex items-center gap-2 max-sm:hidden">
					<span id="{presetsId}-presets" class="text-xs text-muted-foreground">
						{m.view_presets()}
					</span>
					<Segmented
						labelledby="{presetsId}-presets"
						value={presetOf(view)}
						options={PRESETS.map((preset) => ({
							value: preset,
							label: PRESET_NAMES[preset].label(),
							hint: PRESET_NAMES[preset].hint()
						}))}
						onchange={(next) => show(presetView(next as Preset))}
					/>
				</div>
			{/if}
		</div>

		{#if tab === 'document' && phone.current}
			<!-- On a phone one pane at a time (Tobi, 20.10.2026): the four in one bar. -->
			<Segmented
				equal
				class="w-full"
				label={m.view_pane()}
				value={side === 'left' ? view.left : view.right}
				options={[
					{ value: 'pages', label: m.view_pages() },
					{ value: 'text', label: m.view_text() },
					{ value: 'form', label: m.view_form() },
					{ value: 'facts', label: m.view_facts() }
				]}
				onchange={showOnPhone}
			/>
		{/if}

		{#if tab === 'document'}
			{#snippet leftSwitch()}
				<Segmented
					size="sm"
					names="@xl"
					label={m.view_left()}
					value={view.left}
					options={[
						{ value: 'pages', label: m.view_pages(), icon: File },
						{ value: 'text', label: m.view_text(), icon: TextAlignStart }
					]}
					onchange={(next) => show({ ...view, left: next as Left })}
				/>
			{/snippet}
			{#snippet rightSwitch()}
				<Segmented
					size="sm"
					names="wide"
					label={m.view_right()}
					value={view.right}
					options={[
						{ value: 'form', label: m.view_form(), icon: SquarePen },
						{ value: 'facts', label: m.view_facts(), icon: ListChecks }
					]}
					onchange={(next) => show({ ...view, right: next as Right })}
				/>
			{/snippet}
			<div
				class="grid grid-cols-[minmax(0,1fr)] gap-6 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_28rem] lg:grid-rows-[minmax(0,1fr)]"
			>
				<div
					class="flex min-h-[32rem] flex-col lg:min-h-0"
					hidden={phone.current && side !== 'left'}
				>
					{#if view.left === 'pages' || opened.has('pages')}
						<div class="flex min-h-0 flex-1 flex-col" hidden={view.left !== 'pages'}>
							<!-- Anew once the archive exists: the marks belong to it, not to the original. -->
							{#key `${id}:${archive}`}
								{#if archive || !document.page_count}
									<PdfViewer
										bind:this={viewer}
										sources={viewerSources(document, archive)}
										label={document.title}
										marks={archive
											? [...(view.right === 'form' ? marks : factMarks), ...codeMarks]
											: []}
										end={paneSwitch(leftSwitch)}
									/>
								{:else}
									<PageImages
										documentId={id}
										pageCount={document.page_count}
										label={document.title}
										end={paneSwitch(leftSwitch)}
									/>
								{/if}
							{/key}
						</div>
					{/if}
					{#if view.left === 'text' || opened.has('text')}
						<div class="flex min-h-0 flex-1 flex-col" hidden={view.left !== 'text'}>
							<DocumentText
								bind:this={textPane}
								documentId={id}
								vision={reading?.vision ?? false}
								hasText={hasText(document.processing)}
								marks={view.right === 'facts' ? textMarks : []}
								quotes={view.right === 'form' ? fieldQuotes : []}
								end={paneSwitch(leftSwitch)}
							/>
						</div>
					{/if}
				</div>
				<div
					class="flex min-h-[32rem] flex-col lg:min-h-0"
					hidden={phone.current && side !== 'right'}
				>
					{#if view.right === 'facts' || opened.has('facts')}
						<div class="flex min-h-0 flex-1 flex-col" hidden={view.right !== 'facts'}>
							<DocumentFacts
								{facts}
								documentId={id}
								{lookup}
								topicId={document.topic_id}
								admin={session.isAdmin}
								onmark={markFact}
								onshowcode={showCode}
								onchanged={reloadFacts}
								end={paneSwitch(rightSwitch)}
							/>
						</div>
					{/if}
					{#if view.right === 'form' || opened.has('form')}
						<div class="flex min-h-0 flex-1 flex-col" hidden={view.right !== 'form'}>
							{#if lookup}
								{#key id}
									<DocumentForm
										{document}
										{lookup}
										{review}
										{editable}
										next={nextUp}
										onsaved={(updated) => (document = updated)}
										onenabled={() => loadLookup().then((value) => (lookup = value), reportError)}
										onconfirmed={confirmed}
										onmarks={(next) => (marks = next)}
										onquotes={(next) => (fieldQuotes = next)}
										factCounts={facts ? factCounts(facts) : null}
										factsHref={viewHref(page.url, { ...view, right: 'facts' })}
										onreveal={reveal}
										end={paneSwitch(rightSwitch)}
									/>
								{/key}
							{:else}
								<p class="text-muted-foreground">{m.loading()}</p>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		{:else if tab === 'metadata'}
			<DocumentFiles documentId={id} />
		{:else if tab === 'log'}
			<div class="lg:min-h-0 lg:flex-1">
				<DocumentLog
					{document}
					{graph}
					{manageable}
					{lookup}
					onreprocess={() => header?.startReprocess()}
				/>
			</div>
		{/if}
	{/if}
</div>
