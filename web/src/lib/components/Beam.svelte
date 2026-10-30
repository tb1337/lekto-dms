<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import X from '@lucide/svelte/icons/x';
	import { toast } from 'svelte-sonner';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import type { components } from '#lib/api/schema.ts';
	import { beamTo, closeBeam, type BeamSource } from '#lib/beam.svelte.ts';
	import IconButton from '#lib/components/IconButton.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import PageImages from '#lib/components/document/PageImages.svelte';
	import Eyebrow from '#lib/components/page/Eyebrow.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Sheet from '#lib/components/ui/sheet/index.ts';
	import { documentHref } from '#lib/candidates.ts';
	import { inboxDocument, type Mark } from '#lib/document-view.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { kindLabel } from '#lib/identifiers.ts';
	import { latest } from '#lib/latest.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { jumpTo } from '#lib/way-back.ts';

	// The Beam (web/DESIGN.md, "Beam"): a document's pages in a sheet from the right, 640 px on
	// a desktop and the whole screen on a phone, over the place it was opened from, a dialog
	// included. It only shows: a head with the title, contact, type and date, the documents to
	// page through (arrows, ← →), the pages zoomed as in the document view, and "Dokument
	// öffnen", which jumps there with the way back to here. Its state is the history entry's
	// (`beam.svelte.ts`): the back button closes it, a reload brings it back. A document that is
	// gone or out of reach closes it, and a toast says why. With a `source` it marks each place
	// the value stands, the fact's own with a halo and its kind, and scrolls there; it pages
	// through the places ("Fundstelle 2 von 5"). It never looks for a value itself: the places
	// come from the endpoint that names them.
	type Document = components['schemas']['DocumentDetails'];
	type PlaceOut = components['schemas']['PlaceOut'];

	const beam = $derived(page.state.beam ?? null);
	const id = $derived(beam ? (beam.ids[beam.index] ?? null) : null);
	let document = $state<Document | null>(null);
	let names = $state<{ contact: string | null; type: string | null }>({
		contact: null,
		type: null
	});
	let problem = $state<string | null>(null);
	let sheet = $state<HTMLElement | null>(null);
	let images = $state<PageImages | null>(null);
	// The places of the source, by document, and which source they are of.
	let places = $state<{ key: string; byDocument: Map<string, PlaceOut> } | null>(null);
	const begin = latest();
	const beginPlaces = latest();
	const sourceKey = $derived(beam?.source ? JSON.stringify(beam.source) : null);

	async function load(wanted: string) {
		const current = begin();
		document = null;
		problem = null;
		names = { contact: null, type: null };
		try {
			const found = await unwrap(
				api.GET('/api/v1/documents/{id}', { params: { path: { id: wanted } } })
			);
			if (!current()) return;
			document = found;
			void loadNames(found, current);
		} catch (error) {
			if (!current()) return;
			if (error instanceof ApiError && error.status === 404) {
				toast.info(m.beam_gone());
				closeBeam();
				return;
			}
			problem = describeError(error);
		}
	}

	/** The names of its contact and type, for the head; without them it shows the rest. */
	async function loadNames(shown: Document, current: () => boolean) {
		const [contact, type] = await Promise.allSettled([
			shown.contact_id
				? unwrap(api.GET('/api/v1/contacts/{id}', { params: { path: { id: shown.contact_id } } }))
				: null,
			shown.document_type_id
				? unwrap(
						api.GET('/api/v1/document-types/{id}', {
							params: { path: { id: shown.document_type_id } }
						})
					)
				: null
		]);
		if (!current()) return;
		names = {
			contact: contact.status === 'fulfilled' ? (contact.value?.name ?? null) : null,
			type: type.status === 'fulfilled' ? (type.value?.name ?? null) : null
		};
	}

	$effect(() => {
		if (id) void load(id);
	});

	/** The places of the Beam's source; without them it shows the pages unmarked. */
	async function loadPlaces(source: BeamSource, key: string) {
		const current = beginPlaces();
		try {
			const found =
				source.kind === 'open'
					? (
							await unwrap(
								api.GET('/api/v1/identifiers/open/{kind}/{ref}', {
									params: { path: { kind: source.identifier, ref: source.ref } }
								})
							)
						).places
					: (
							await unwrap(
								api.GET('/api/v1/identifiers/places/{kind}/{ref}', {
									params: { path: { kind: source.identifier, ref: source.ref } }
								})
							)
						).places;
			if (!current()) return;
			places = { key, byDocument: new Map(found.map((place) => [place.document_id, place])) };
		} catch {
			// The pages show all the same, unmarked.
		}
	}

	$effect(() => {
		const source = beam?.source;
		if (!source || !sourceKey || places?.key === sourceKey) return;
		void loadPlaces(source, sourceKey);
	});

	const place = $derived(
		id && places && places.key === sourceKey ? (places.byDocument.get(id) ?? null) : null
	);
	// Each place on each of its pages; the fact's own one with its kind and a halo.
	const marks = $derived.by<Mark[]>(() => {
		if (!place || !beam?.source) return [];
		const kind = kindLabel(beam.source.identifier);
		return place.occurrences.flatMap((occurrence, index) =>
			occurrence.locations.map((location) => ({
				key: `place-${index}`,
				label: occurrence.own ? kind : '',
				page: location.page,
				boxes: location.boxes,
				derived: false,
				pinned: occurrence.own
			}))
		);
	});

	// To the fact's own place (else the first) once the pages stand.
	$effect(() => {
		const occurrence = place?.occurrences.find((item) => item.own) ?? place?.occurrences[0];
		const target = occurrence?.locations[0];
		if (!target || !images || !document) return;
		const shown = images;
		const timer = setTimeout(() => shown.reveal(target), 120);
		return () => clearTimeout(timer);
	});

	const meta = $derived(
		document
			? [
					names.contact,
					names.type,
					document.document_date ? formatDate(document.document_date) : null
				]
					.filter(Boolean)
					.join(' · ')
			: ''
	);

	function keydown(event: KeyboardEvent) {
		if (!beam || event.altKey || event.ctrlKey || event.metaKey) return;
		const target = event.target as HTMLElement | null;
		// The pages' own keys (+ − 0, scrolling) and fields stay theirs.
		if (target?.closest('[role="document"], input, textarea, select')) return;
		if (event.key === 'ArrowLeft') beamTo(beam.index - 1);
		else if (event.key === 'ArrowRight') beamTo(beam.index + 1);
		else return;
		event.preventDefault();
	}

	function open() {
		if (!beam || !id) return;
		void jumpTo(beam.inbox ? inboxDocument(id) : documentHref(id), beam.from);
	}
</script>

<Sheet.Root
	open={beam !== null}
	onOpenChange={(next) => {
		if (!next) closeBeam();
	}}
>
	<!-- The sheet itself takes the focus: ← → work at once, and no tooltip shows unasked. The
	     page behind stays sharp: a dialog beside it stays readable. -->
	<Sheet.Content
		bind:ref={sheet}
		data-beam
		side="right"
		overlayClass="supports-backdrop-filter:backdrop-blur-none"
		showCloseButton={false}
		tabindex={-1}
		onOpenAutoFocus={(event) => {
			event.preventDefault();
			sheet?.focus();
		}}
		onkeydown={keydown}
		class="gap-0 p-0 outline-none data-[side=right]:w-full data-[side=right]:sm:max-w-[40rem]"
	>
		<div class="flex shrink-0 items-start gap-3 py-3 pr-2 pl-4 sm:pl-5">
			<div class="min-w-0 flex-1">
				<Eyebrow>{m.beam_name()}</Eyebrow>
				<Sheet.Title class="truncate text-base font-semibold">
					{document?.title ?? '…'}
				</Sheet.Title>
				<Sheet.Description class="truncate text-sm text-muted-foreground">
					{meta}
				</Sheet.Description>
			</div>
			<Sheet.Close>
				{#snippet child({ props })}
					<IconButton {...props} label={m.close()} side="bottom">
						<X aria-hidden="true" />
					</IconButton>
				{/snippet}
			</Sheet.Close>
		</div>
		{#if beam && beam.ids.length > 1}
			<div class="flex shrink-0 items-center gap-2 px-4 pb-3 sm:px-5">
				<IconButton
					variant="outline"
					size="sm"
					label={m.beam_previous()}
					disabled={beam.index === 0}
					onclick={() => beamTo(beam.index - 1)}
				>
					<ChevronLeft aria-hidden="true" />
				</IconButton>
				<span class="min-w-28 text-center text-sm tabular-nums" aria-live="polite">
					{beam.source
						? m.beam_place_position({ current: beam.index + 1, total: beam.ids.length })
						: m.beam_position({ current: beam.index + 1, total: beam.ids.length })}
				</span>
				<IconButton
					variant="outline"
					size="sm"
					label={m.beam_next()}
					disabled={beam.index === beam.ids.length - 1}
					onclick={() => beamTo(beam.index + 1)}
				>
					<ChevronRight aria-hidden="true" />
				</IconButton>
			</div>
		{/if}
		<div class="flex min-h-0 flex-1 flex-col border-t bg-surface p-3">
			{#if problem}
				<LoadProblem {problem} onretry={() => id && load(id)} />
			{:else if !document}
				<Loading class="py-16 text-center" />
			{:else if !document.page_count}
				<p class="py-16 text-center text-sm text-muted-foreground">{m.beam_no_pages()}</p>
			{:else}
				{#key document.id}
					<PageImages
						bind:this={images}
						{marks}
						documentId={document.id}
						pageCount={document.page_count}
						label={m.beam_pages({ title: document.title })}
						note={null}
						start="one"
					/>
				{/key}
			{/if}
		</div>
		<div
			class="flex shrink-0 justify-end border-t px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-5"
		>
			<Button variant="outline" class="max-sm:w-full" disabled={!document} onclick={open}>
				{m.beam_open_document()}
				<ArrowRight aria-hidden="true" />
			</Button>
		</div>
	</Sheet.Content>
</Sheet.Root>
