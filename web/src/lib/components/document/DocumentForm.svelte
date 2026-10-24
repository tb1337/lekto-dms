<script lang="ts">
	import FileText from '@lucide/svelte/icons/file-text';
	import Globe from '@lucide/svelte/icons/globe';
	import Layers from '@lucide/svelte/icons/layers';
	import ListChecks from '@lucide/svelte/icons/list-checks';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Shapes from '@lucide/svelte/icons/shapes';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { onDestroy, untrack, type Snippet } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import ContactAvatar from '#lib/components/ContactAvatar.svelte';
	import { moveTargets, retryProcessing } from '#lib/components/document/actions.ts';
	import FieldGroup from '#lib/components/document/FieldGroup.svelte';
	import FieldShell from '#lib/components/document/FieldShell.svelte';
	import FilingBox from '#lib/components/document/FilingBox.svelte';
	import PaneHead from '#lib/components/document/PaneHead.svelte';
	import TopicInput from '#lib/components/document/TopicInput.svelte';
	import SearchSelect, { type SearchOption } from '#lib/components/SearchSelect.svelte';
	import GroupChips from '#lib/components/GroupChips.svelte';
	import FieldValueInput from '#lib/components/FieldValueInput.svelte';
	import RuleEffects from '#lib/components/rules/RuleEffects.svelte';
	import TagPicker from '#lib/components/TagPicker.svelte';
	import TypeIcon from '#lib/components/TypeIcon.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { describeValue, fieldLabel } from '#lib/describe.ts';
	import {
		fieldEvidence,
		marksOf,
		placesApply,
		type Mark,
		type Place,
		type Review
	} from '#lib/document-view.ts';
	import { describeError, fieldErrors as fieldMessages } from '#lib/errors.ts';
	import { factsSummary } from '#lib/facts.ts';
	import {
		confirmHint,
		initialChoice,
		openFiling,
		openSpaceCheck,
		type Filing,
		type Viewer
	} from '#lib/filing.ts';
	import { sameValue, toApi, toInput, type ApiValue, type InputValue } from '#lib/fields.ts';
	import {
		fieldsFor,
		spaceOptions,
		type FieldDefinition,
		type Lookup,
		userLabel
	} from '#lib/masterdata.svelte.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { labelled, reasonsText } from '#lib/reasons.ts';
	import { phone } from '#lib/phone.svelte.ts';
	import { fieldId, initialValue, isRuleField, type ReviewValue } from '#lib/review.ts';
	import { session } from '#lib/session.svelte.ts';
	import { suggestedSpace, unseenBy, unseenHere } from '#lib/space-suggestion.ts';
	import { cn } from '#lib/utils.ts';
	import { above, normalise, ofScope } from '#lib/tags.ts';

	type Document = components['schemas']['DocumentDetails'];
	type Patch = components['schemas']['DocumentPatch'];
	type Preview = components['schemas']['DocumentPreviewOut'];
	type Confirm = components['schemas']['ConfirmRequest'];

	// The metadata of a document in three groups: basics, global fields, the fields of its
	// type. While it waits in the inbox, the open fields are cards and "Confirm" decides them
	// all at once (with any other change); otherwise a change is shown as a dry run before it
	// is saved. Hovering a field marks its quote on the pages (`onmarks`) and in the text
	// (`onquotes`), a click on the page of a quote jumps there (`onreveal`).
	let {
		document,
		lookup,
		review,
		editable,
		next = null,
		onsaved,
		onconfirmed,
		onmarks,
		onquotes,
		onreveal,
		onenabled,
		factCounts = null,
		factsHref = '',
		onmove,
		end
	}: {
		document: Document;
		lookup: Lookup;
		/** What the model proposed: editors and admins only, else null. */
		review: Review | null;
		editable: boolean;
		/** The document offered to open after confirming: the inbox's next one that waits for a
		 * decision. */
		next?: string | null;
		onsaved: (document: Document) => void;
		/** After confirming: the document to open next, or null for the inbox. */
		onconfirmed: (next: string | null) => void;
		onmarks: (marks: Mark[]) => void;
		/** The quotes of the fields marked, to mark in the text. */
		onquotes?: (quotes: string[]) => void;
		onreveal: (place: Place) => void;
		/** An admin's choice enabled the topic at the contact: the master data changed. */
		onenabled?: () => void;
		/** What the document shows of its contact, counted; a chip at the contact leads there. */
		factCounts?: { evidence: number; unknown: number; codes: number } | null;
		/** Where the facts are: the other pane of the document tab. */
		factsHref?: string;
		/** "Move" in the filing box: the move dialog of the document's head. */
		onmove?: () => void;
		/** At the end of the head: the pane's switch. */
		end?: Snippet;
	} = $props();

	// The chip's text: what there is, counted; nothing for none.
	const factsChip = $derived(factCounts ? factsSummary(factCounts) : '');

	let title = $state('');
	let date = $state('');
	let contact = $state('');
	let topic = $state('');
	let documentType = $state('');
	let tags = $state<string[]>([]);
	let values = $state<Record<string, InputValue>>({});
	// The filing chosen while the space check waits: a space, `other` for "Another space"
	// (then `otherSpace`), or empty for none yet.
	let spaceChoice = $state('');
	let otherSpace = $state('');
	let openNext = $state(true);
	let busy = $state(false);
	let preview = $state<Preview | null>(null);
	let patch = $state<Patch>({});
	let fieldErrors = $state<Record<string, string>>({});
	// Period fields whose text cannot be read (by field id): their value is not what they show,
	// so the form does not save or confirm while there is one (`PeriodInput`).
	let unreadable = $state<Record<string, boolean>>({});
	const blocked = $derived(Object.values(unreadable).some(Boolean));
	let formError = $state<string | null>(null);

	const evidence = $derived(fieldEvidence(review));
	const openChecks = $derived(review ? review.open.flatMap((node) => node.fields) : []);
	const failedNode = $derived(review?.open.find((node) => node.outcome === 'failed') ?? null);
	// Waiting in the inbox as the API sees it: yellow or red, not being processed, no node
	// still running after a failure.
	const confirmable = $derived(
		(document.lane === 'yellow' || document.lane === 'red') &&
			['review', 'failed', 'completed'].includes(document.processing.status) &&
			!document.processing.nodes.some((state) => state.status === 'running')
	);
	const reviewing = $derived(review !== null && review.open.length > 0 && confirmable);
	// The fields still to decide, counted in the head.
	const undecided = $derived([...evidence.values()].filter((entry) => entry.open).length);
	const decisions = $derived(openChecks.filter((check) => !isRuleField(check.field)));
	const ruleNotes = $derived(
		openChecks.filter((check) => check.field === 'review' || check.field === 'title')
	);
	// Uncertain nodes without a field of their own (no language model, nothing recognised).
	const nodeNotes = $derived(
		review?.open.filter((node) => node.outcome === 'uncertain' && node.fields.length === 0) ?? []
	);
	const hasSpace = $derived(reviewing && openChecks.some((check) => check.field === 'space'));
	// Something to confirm. A failed node alone is repeated, not confirmed; its document can
	// still be changed (dry run and save).
	const confirming = $derived(reviewing && (!failedNode || decisions.length > 0 || hasSpace));
	// The space Lekto suggests (the judge's open check): chosen from the start.
	const spaceSuggestion = $derived(hasSpace ? suggestedSpace(review?.open ?? []) : null);
	// Whom the document names who would not see it where the check leads (a warning).
	const spaceUnseen = $derived(hasSpace ? unseenBy(review?.open ?? []) : []);
	// The same when the judge settled the space by itself (a green document stays, or moved).
	const settledUnseen = $derived(
		hasSpace ? [] : unseenHere(review?.nodes ?? [], document.space_id, lookup)
	);
	const viewer: Viewer = $derived({ id: session.user?.id, admin: session.isAdmin });
	// Confirmed into a space the caller edits (an admin: any), or handed over into another user's
	// personal space.
	const spaceChoices = $derived(spaceOptions(lookup.spaces, lookup.users, session.user));
	// The filing box while the space check waits: the choices the signals offer.
	const filing: Filing | null = $derived.by(() => {
		const check = hasSpace ? openSpaceCheck(review?.open ?? []) : null;
		return check ? openFiling(check, document.space_id, lookup, viewer, spaceChoices) : null;
	});
	// "Another space": the caller's other choices.
	const otherChoices = $derived(
		spaceChoices.filter(
			(option) =>
				option.value !== document.space_id &&
				!filing?.options.some((offered) => offered.value === option.value)
		)
	);
	// Where the document goes on confirming: empty while nothing is chosen.
	const spaceTarget = $derived(spaceChoice === 'other' ? otherSpace : spaceChoice);
	// "Move" in the filing box: there is somewhere to move it (the head's button says the same).
	const canMove = $derived(moveTargets(lookup, session.user, document.space_id).length > 0);
	const filingHint = $derived(
		filing ? confirmHint(spaceTarget, document.space_id, lookup, viewer) : null
	);

	const snapshot = () =>
		JSON.stringify([
			title,
			date,
			contact,
			topic,
			documentType,
			tags,
			values,
			spaceChoice,
			otherSpace
		]);
	let baseline: { id: string; form: string; reviewing: boolean } | null = null;

	function assign(key: string, value: ReviewValue) {
		const id = fieldId(key);
		if (id !== null) values[id] = value as InputValue;
		else if (key === 'contact') chooseContact(value as string);
		else if (key === 'topic') topic = value as string;
		else if (key === 'document_type') documentType = value as string;
		else if (key === 'document_date') date = value as string;
		else if (key === 'tags') tags = [...(value as string[])];
	}

	// The form starts from the stored state (and, for open fields, the model's suggestions),
	// and again after the document changed, unless the user has changed something meanwhile:
	// an event must not wipe their input.
	function fromDocument() {
		title = document.title;
		date = document.document_date ?? '';
		contact = document.contact_id ?? '';
		topic = document.topic_id ?? '';
		documentType = document.document_type_id ?? '';
		tags = [...document.tag_ids];
		values = Object.fromEntries(
			lookup.fields.map((field) => [field.id, toInput(field.data_type, document.fields[field.id])])
		);
		spaceChoice = '';
		otherSpace = '';
		if (reviewing) {
			for (const check of decisions)
				assign(check.field, initialValue(check, document, lookup.fields));
			if (filing) spaceChoice = initialChoice(filing);
		}
		baseline = { id: document.id, form: snapshot(), reviewing };
	}

	/** The field's value as the document stores it, in the form of the API. */
	function stored(key: string): ApiValue | string[] | null {
		const id = fieldId(key);
		if (id !== null) return document.fields[id] ?? null;
		if (key === 'contact') return document.contact_id;
		if (key === 'topic') return document.topic_id;
		if (key === 'document_type') return document.document_type_id;
		if (key === 'document_date') return document.document_date;
		if (key === 'tags') return document.tag_ids;
		return null;
	}

	// The topics of the chosen contact; an admin may choose any (it is then enabled at the
	// contact). Another contact keeps the topic only if it enables it, as the API does.
	const enabledTopics = $derived(
		lookup.contacts.find((entry) => entry.id === contact)?.topic_ids ?? []
	);
	// The tags above those set: not offered, the tag set says more.
	const tagsAbove = $derived(above(lookup.tags, tags));
	const topicChoices = $derived(
		ofScope(lookup.tags, 'topic').filter(
			(option) =>
				option.id === topic ||
				(contact !== '' && (session.isAdmin || enabledTopics.includes(option.id)))
		)
	);
	const enablesTopic = $derived(topic !== '' && contact !== '' && !enabledTopics.includes(topic));
	// Only a contact with topics has the field (Tobi, 20.10.2026): it appears when such a
	// contact is chosen. A topic the document has stays in view, to be seen and removed.
	const showsTopic = $derived(enabledTopics.length > 0 || topic !== '');
	const topicCheck = $derived(evidence.get('topic')?.check);
	// Lekto suggests a topic it did not set (a topic never waits): a card with the candidates.
	const topicAdvice = $derived(
		topic === '' &&
			topicCheck !== undefined &&
			(topicCheck.value ?? null) === null &&
			(topicCheck.candidates?.length ?? 0) > 0
	);

	function chooseContact(value: string) {
		contact = value;
		const topics = lookup.contacts.find((entry) => entry.id === value)?.topic_ids ?? [];
		if (topic !== '' && !topics.includes(topic)) topic = '';
	}

	$effect(() => {
		void document;
		void lookup.fields;
		void reviewing;
		void decisions;
		void filing;
		untrack(() => {
			const edited = baseline?.id === document.id && snapshot() !== baseline.form;
			if (!edited) fromDocument();
			else if (reviewing && baseline && !baseline.reviewing) {
				// It came into the inbox while the user typed: their input stays, the open
				// fields they left alone take the suggestions.
				for (const check of decisions) {
					if (JSON.stringify(current(check.field)) === JSON.stringify(stored(check.field))) {
						assign(check.field, initialValue(check, document, lookup.fields));
					}
				}
				if (spaceChoice === '' && filing) spaceChoice = initialChoice(filing);
				baseline = { ...baseline, reviewing: true };
			}
		});
	});

	// Fields that fit the chosen type, and those the document has without fitting it.
	const fitting = $derived(fieldsFor(lookup.fields, documentType || null));
	const chosenContact = $derived(lookup.contacts.find((entry) => entry.id === contact));
	const chosenType = $derived(lookup.documentTypes.find((entry) => entry.id === documentType));
	const globalFields = $derived(fitting.filter((field) => field.document_type_ids === null));
	const typeFields = $derived(fitting.filter((field) => field.document_type_ids !== null));
	const otherFields = $derived(
		lookup.fields.filter(
			(field) => !fitting.includes(field) && document.fields[field.id] !== undefined
		)
	);
	const shown = $derived([...globalFields, ...typeFields, ...otherFields]);
	const typeName = $derived(
		lookup.documentTypes.find((entry) => entry.id === documentType)?.name ?? null
	);
	/** A contact or type an admin makes from the search, in its dialog with `name` filled in
	 * (the lists load again); null when the dialog closed without. */
	async function createMasterData(
		kind: 'contacts' | 'document-types',
		name: string
	): Promise<SearchOption | null> {
		const made = await masterDataDialogs.create(kind, name);
		return made ? { value: made.id, label: made.name } : null;
	}

	/** What differs from the stored document, in the form of the API (null removes a value). */
	function buildPatch(): Patch {
		const next: Patch = {};
		if (title.trim() !== document.title) next.title = title.trim();
		if ((date || null) !== document.document_date) next.document_date = date || null;
		if ((contact || null) !== document.contact_id) next.contact_id = contact || null;
		const chosen = topic || null;
		const kept = document.topic_id ?? null;
		if ('contact_id' in next) {
			// Another contact keeps the topic if it enables it and clears it otherwise (the API
			// does both): only the person's own choice is sent. Another topic; the stored one
			// cleared where the contact enables it; or the stored one chosen again where it
			// does not (an admin's choice enables it there).
			const enabled = (id: string) => enabledTopics.includes(id);
			if (chosen !== null ? chosen !== kept || !enabled(chosen) : kept !== null && enabled(kept)) {
				next.topic_id = chosen;
			}
		} else if (chosen !== kept) next.topic_id = chosen;
		if ((documentType || null) !== document.document_type_id) {
			next.document_type_id = documentType || null;
		}
		if (JSON.stringify([...tags].sort()) !== JSON.stringify([...document.tag_ids].sort())) {
			next.tag_ids = [...tags];
		}
		const changed: Record<string, ApiValue | null> = {};
		for (const field of shown) {
			const value = toApi(field.data_type, values[field.id]);
			if (!sameValue(value, document.fields[field.id])) changed[field.id] = value;
		}
		if (Object.keys(changed).length > 0) next.fields = changed;
		return next;
	}

	/**
	 * The confirmation: every change, and a decision for every open field (its value, or null
	 * for none). After a corrected document type the fields of the new type are extracted
	 * again, so their open values are not sent.
	 */
	function buildConfirm(): Confirm {
		const changes = buildPatch();
		const typeChanged = 'document_type_id' in changes;
		const fields: Record<string, ApiValue | null> = { ...(changes.fields ?? {}) } as Record<
			string,
			ApiValue | null
		>;
		for (const check of decisions) {
			const id = fieldId(check.field);
			if (id !== null) {
				const field = lookup.fields.find((entry) => entry.id === id);
				// Extracted again for the new type: a suggestion must not count as the owner's.
				// A field set by hand is never extracted: what the owner entered stays.
				if (typeChanged && field?.assignment !== 'manual') delete fields[id];
				else if (field) fields[id] = toApi(field.data_type, values[id]);
			} else if (check.field === 'contact') changes.contact_id = contact || null;
			else if (check.field === 'topic') changes.topic_id = topic || null;
			else if (check.field === 'document_type') changes.document_type_id = documentType || null;
			else if (check.field === 'document_date') changes.document_date = date || null;
			else if (check.field === 'tags') changes.tag_ids = [...tags];
		}
		if (Object.keys(fields).length > 0) changes.fields = fields;
		else delete changes.fields;
		const moving = hasSpace && spaceTarget !== '' && spaceTarget !== document.space_id;
		// The suggested space is accepted as the suggestion; every other field has its decision
		// in `changes` then. After a corrected type the fields are extracted again and have none:
		// the space goes by name.
		const accepting = moving && spaceTarget === spaceSuggestion && !typeChanged;
		return {
			changes,
			accept_suggestions: accepting,
			resume_at: typeChanged ? 'fields' : 'apply_rules',
			...(moving && !accepting ? { space_id: spaceTarget } : {})
		};
	}

	const dirty = $derived(Object.keys(buildPatch()).length > 0);

	function readProblem(error: unknown): void {
		fieldErrors = fieldMessages(error);
		if (error instanceof ApiError && error.problem?.open_fields) {
			formError = m.review_open_fields({
				fields: error.problem.open_fields.map((field) => fieldLabel(field, lookup)).join(', ')
			});
		} else formError = Object.keys(fieldErrors).length === 0 ? describeError(error) : null;
	}

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy || !editable || blocked) return;
		if (confirming) await confirm();
		else await dryRun();
	}

	async function confirm() {
		busy = true;
		formError = null;
		const enabling = session.isAdmin && enablesTopic;
		try {
			const body = buildConfirm();
			const target = body.accept_suggestions ? spaceSuggestion : (body.space_id ?? null);
			const result = await unwrap(
				api.POST('/api/v1/documents/{id}/confirm', {
					params: { path: { id: document.id } },
					body
				})
			);
			baseline = null;
			if (enabling) onenabled?.();
			// The answer says `access: null` when the caller cannot read the document any more.
			const away =
				typeof result === 'object' &&
				result !== null &&
				'access' in result &&
				(result as { access: unknown }).access === null;
			if (!away) toast.success(m.review_confirmed());
			else {
				// Handed over, or into a space the caller only reads, where it is not green yet.
				const receiver = (lookup?.users ?? []).find(
					(other) => other.personal_space_id === target && other.id !== session.user?.id
				);
				toast.success(
					receiver ? m.move_handed_over({ name: userLabel(receiver) }) : m.document_moved_away()
				);
			}
			onconfirmed(openNext ? next : null);
		} catch (error) {
			readProblem(error);
		} finally {
			busy = false;
		}
	}

	async function dryRun() {
		patch = buildPatch();
		if (Object.keys(patch).length === 0) return;
		busy = true;
		try {
			preview = await unwrap(
				api.POST('/api/v1/documents/{id}/dry-run', {
					params: { path: { id: document.id } },
					body: patch
				})
			);
			fieldErrors = {};
			formError = null;
		} catch (error) {
			readProblem(error);
		} finally {
			busy = false;
		}
	}

	async function save() {
		busy = true;
		const enabling = session.isAdmin && enablesTopic && 'topic_id' in patch;
		try {
			const result = await unwrap(
				api.PATCH('/api/v1/documents/{id}', {
					params: { path: { id: document.id } },
					body: patch
				})
			);
			preview = null;
			baseline = null;
			if (enabling) onenabled?.();
			toast.success(m.document_saved());
			if ('title' in result) onsaved(result);
			else {
				// The rules filed the document where the caller can no longer read it.
				toast.info(m.document_moved_away());
				await goto(`${BASE}/documents`);
			}
		} catch (error) {
			preview = null;
			readProblem(error);
		} finally {
			busy = false;
		}
	}

	async function retry() {
		busy = true;
		try {
			await retryProcessing(document.id);
			toast.success(m.retry_started());
		} catch (error) {
			formError = describeError(error);
		} finally {
			busy = false;
		}
	}

	function reset() {
		fieldErrors = {};
		formError = null;
		fromDocument();
	}

	// --- marks in the viewer ------------------------------------------------------------------

	let focused = $state<string | null>(null);
	let pinned = $state<string | null>(null);
	let unpin: ReturnType<typeof setTimeout> | undefined;
	onDestroy(() => clearTimeout(unpin));

	function fieldOf(key: string): FieldDefinition | undefined {
		const id = fieldId(key);
		return id === null ? undefined : lookup.fields.find((field) => field.id === id);
	}

	/** The field's value as the form holds it now, in the form of the API. */
	function current(key: string): ApiValue | string[] | null {
		const field = fieldOf(key);
		if (field) return toApi(field.data_type, values[field.id]);
		if (key === 'contact') return contact || null;
		if (key === 'topic') return topic || null;
		if (key === 'document_type') return documentType || null;
		if (key === 'document_date') return date || null;
		if (key === 'tags') return tags;
		return null;
	}

	function applies(key: string): boolean {
		const found = evidence.get(key);
		return found ? placesApply(found.check, current(key)) : true;
	}

	// The fields marked: hovered or focused, and the one jumped to; their quotes while they
	// still belong to the value.
	const marked = $derived(
		[...new Set([focused, pinned])].flatMap((key) => {
			const found = key === null ? undefined : evidence.get(key);
			return key !== null && found && applies(key) ? [{ key, check: found.check }] : [];
		})
	);
	const marks = $derived(
		marked.flatMap(({ key, check }) =>
			marksOf(key, fieldLabel(key, lookup), check, { pinned: key === pinned })
		)
	);
	const quotes = $derived(
		marked.map(({ check }) => check.evidence?.trim() ?? '').filter((quote) => quote !== '')
	);
	$effect(() => onmarks(marks));
	$effect(() => onquotes?.(quotes));

	function focus(key: string | null) {
		focused = key;
	}

	// A value the signals proposed, taken with a click on its card.
	function take(key: string, value: unknown) {
		assign(key, value as ReviewValue);
	}

	/** A field the chosen type requires (a global one by its own switch). */
	function required(field: FieldDefinition): boolean {
		return field.document_type_ids === null
			? field.required
			: documentType !== '' && field.required_document_type_ids.includes(documentType);
	}

	// On a phone the pages take the place of the form: the mark stays until the next jump.
	function jump(key: string, place: Place) {
		pinned = key;
		clearTimeout(unpin);
		if (!phone.current) unpin = setTimeout(() => (pinned = null), 2500);
		onreveal(place);
	}

	const located = $derived([...evidence.values()].some((entry) => entry.check.locations?.length));
</script>

<form
	class="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border bg-card"
	onsubmit={submit}
	novalidate
	aria-label={m.edit_title()}
>
	<!-- The head only where it holds something: on a phone the pane has no switch. -->
	{#if end || (reviewing && undecided > 0)}
		<PaneHead {end}>
			{#if reviewing && undecided > 0}
				<span
					class="inline-flex h-6 items-center gap-1.5 rounded-full bg-lane-yellow px-2.5 text-xs font-medium text-lane-yellow-foreground"
				>
					<span class="size-[7px] rounded-full bg-lane-yellow-foreground" aria-hidden="true"></span>
					{undecided === 1 ? m.review_undecided_one() : m.review_undecided({ count: undecided })}
				</span>
			{/if}
		</PaneHead>
	{/if}
	<div class="relative flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto bg-surface p-3.5">
		{#if reviewing}
			<div
				class="flex items-start gap-2.5 rounded-xl bg-lane-yellow px-3.5 py-3 text-lane-yellow-foreground"
			>
				<TriangleAlert class="mt-0.5 size-[18px] shrink-0" aria-hidden="true" strokeWidth={2.2} />
				<div class="flex flex-col gap-0.5">
					<p class="font-semibold">{m.review_banner_title()}</p>
					{#if located}<p class="text-sm">
							{phone.current ? m.review_banner_hint_phone() : m.review_banner_hint()}
						</p>{/if}
				</div>
			</div>
		{:else if located}
			<p class="px-1 text-sm text-muted-foreground">
				{phone.current ? m.review_banner_hint_phone() : m.review_banner_hint()}
			</p>
		{/if}

		{#if reviewing && failedNode}
			<div class="flex flex-col gap-3 rounded-2xl border border-destructive/40 bg-card p-4">
				<p class="font-medium">{m.review_failed()}</p>
				{#if failedNode.reason}
					<p class="text-sm">
						{reasonsText(failedNode.reasons, failedNode.reason, labelled(lookup))}
					</p>
				{/if}
				{#if editable}
					<div>
						<Button type="button" variant="outline" disabled={busy} onclick={retry}>
							<RotateCcw aria-hidden="true" />
							{m.retry_node()}
						</Button>
					</div>
				{/if}
			</div>
		{/if}

		{#if reviewing}
			{#each nodeNotes as note (note.node)}
				<p class="rounded-xl border bg-card px-4 py-3 text-sm">
					<span class="font-medium">{NODE_LABELS[note.node]()}:</span>
					{reasonsText(note.reasons, note.reason, labelled(lookup))}
				</p>
			{/each}
			{#each ruleNotes as note (note.field)}
				<p class="rounded-xl border bg-card px-4 py-3 text-sm">
					<span class="font-medium">{fieldLabel(note.field, lookup)}:</span>
					{reasonsText(note.reasons, note.reason, { field: (name) => fieldLabel(name, lookup) })}
				</p>
			{/each}
		{/if}

		<!-- What is to decide about the filing comes first (Tobi, 22.10.2026); else it waits below
		     the fields. -->
		{#if filing}
			<FilingBox
				{document}
				{lookup}
				{viewer}
				{filing}
				bind:choice={spaceChoice}
				bind:other={otherSpace}
				otherOptions={otherChoices}
				unseen={spaceUnseen}
				{editable}
			/>
		{/if}

		<FieldGroup
			id="group-basics"
			icon={FileText}
			title={m.group_basics()}
			hint={m.group_basics_hint()}
		>
			<FieldShell
				key="title"
				label={m.field_title()}
				inputId="doc-title"
				{lookup}
				active={focused === 'title'}
				onfocus={focus}
				onjump={jump}
			>
				<Input
					id="doc-title"
					bind:value={title}
					disabled={!editable}
					aria-invalid={fieldErrors.title ? true : undefined}
				/>
				{#if fieldErrors.title}<p class="text-sm text-destructive">{fieldErrors.title}</p>{/if}
			</FieldShell>
			<FieldShell
				key="document_date"
				label={m.field_date()}
				inputId="doc-date"
				evidence={evidence.get('document_date')}
				{lookup}
				review={reviewing}
				applies={applies('document_date')}
				active={focused === 'document_date' || pinned === 'document_date'}
				onfocus={focus}
				onjump={jump}
			>
				<Input id="doc-date" type="date" bind:value={date} disabled={!editable} />
			</FieldShell>
			<FieldShell
				key="contact"
				label={m.field_contact()}
				inputId="doc-contact"
				evidence={evidence.get('contact')}
				{lookup}
				review={reviewing}
				applies={applies('contact')}
				active={focused === 'contact' || pinned === 'contact'}
				onfocus={focus}
				onjump={jump}
				onpick={take}
			>
				<div class="flex min-w-0 items-center gap-2">
					{#if chosenContact}<ContactAvatar contact={chosenContact} size="md" />{/if}
					<SearchSelect
						id="doc-contact"
						value={contact}
						disabled={!editable}
						options={lookup.contacts.map((entry) => ({
							value: entry.id,
							label: entry.name,
							keywords: entry.aliases?.join(' ')
						}))}
						placeholder={m.value_unset()}
						noneLabel={m.value_unset()}
						searchLabel={session.isAdmin ? m.picker_search_create() : m.assignment_search()}
						onchange={chooseContact}
						create={session.isAdmin ? (name) => createMasterData('contacts', name) : undefined}
					/>
				</div>
				<GroupChips
					tags={lookup.tags}
					ids={lookup.contacts.find((entry) => entry.id === contact)?.group_ids ?? []}
					class="mt-1.5"
				/>
				{#if factsChip}
					<a
						href={factsHref}
						class="mt-1.5 inline-flex w-fit items-center gap-1.5 rounded-full bg-lane-green px-2.5 py-1 text-xs font-medium text-lane-green-foreground hover:underline"
					>
						<ListChecks class="size-3.5" aria-hidden="true" />
						{factsChip}
					</a>
				{/if}
			</FieldShell>
			{#if showsTopic}
				<FieldShell
					key="topic"
					label={m.field_topic()}
					inputId="doc-topic"
					evidence={evidence.get('topic')}
					{lookup}
					review={reviewing}
					advice={topicAdvice}
					quoted={false}
					applies={applies('topic')}
					active={focused === 'topic' || pinned === 'topic'}
					onfocus={focus}
					onjump={jump}
					onpick={take}
				>
					<!-- An admin creates a topic here, too; saving enables it at the contact. -->
					<TopicInput
						id="doc-topic"
						bind:value={topic}
						topics={topicChoices}
						all={lookup.tags}
						disabled={!editable ||
							contact === '' ||
							(topicChoices.length === 0 && !session.isAdmin)}
						placeholder={contact === '' ? m.topic_no_contact() : m.value_unset()}
						creating={session.isAdmin && contact !== ''}
					/>
					{#if enablesTopic && session.isAdmin}
						<p class="mt-1 text-xs text-muted-foreground">{m.topic_enables_hint()}</p>
					{/if}
				</FieldShell>
			{/if}
			<FieldShell
				key="document_type"
				label={m.field_document_type()}
				inputId="doc-type"
				evidence={evidence.get('document_type')}
				{lookup}
				review={reviewing}
				applies={applies('document_type')}
				active={focused === 'document_type' || pinned === 'document_type'}
				onfocus={focus}
				onjump={jump}
				onpick={take}
			>
				<div class="flex min-w-0 items-center gap-2">
					{#if chosenType?.icon}
						<span class="grid size-8 shrink-0 place-items-center text-muted-foreground">
							<TypeIcon icon={chosenType.icon} class="size-5" />
						</span>
					{/if}
					<SearchSelect
						id="doc-type"
						bind:value={documentType}
						disabled={!editable}
						options={lookup.documentTypes.map((entry) => ({ value: entry.id, label: entry.name }))}
						placeholder={m.value_unset()}
						noneLabel={m.value_unset()}
						searchLabel={session.isAdmin ? m.picker_search_create() : m.assignment_search()}
						create={session.isAdmin
							? (name) => createMasterData('document-types', name)
							: undefined}
					/>
				</div>
				<GroupChips
					tags={lookup.tags}
					ids={lookup.documentTypes.find((entry) => entry.id === documentType)?.group_ids ?? []}
					class="mt-1.5"
				/>
			</FieldShell>
			<FieldShell
				key="tags"
				label={m.field_tags()}
				inputId="doc-tags"
				evidence={evidence.get('tags')}
				{lookup}
				review={reviewing}
				applies={applies('tags')}
				active={focused === 'tags' || pinned === 'tags'}
				onfocus={focus}
				onjump={jump}
			>
				<!-- A tag set below another replaces it, as the API keeps them; tags above one set
				are not offered. -->
				<TagPicker
					id="doc-tags"
					label={m.field_tags()}
					labelledby="doc-tags-label"
					title={m.field_tags()}
					scope="document"
					tags={lookup.tags}
					selected={tags}
					onchange={(next) => (tags = normalise(lookup.tags, next))}
					offered={(tag) => !tagsAbove.has(tag.id)}
					disabled={!editable}
				/>
			</FieldShell>
		</FieldGroup>

		{#snippet fieldShell(field: FieldDefinition)}
			{@const key = `field:${field.id}`}
			<FieldShell
				{key}
				label={field.name}
				inputId="field-{field.id}"
				evidence={evidence.get(key)}
				{lookup}
				review={reviewing}
				applies={applies(key)}
				active={focused === key || pinned === key}
				required={required(field)}
				byHand={field.assignment === 'manual'}
				hint={field.description}
				onfocus={focus}
				onjump={jump}
			>
				<FieldValueInput
					{field}
					bind:value={values[field.id]}
					id="field-{field.id}"
					disabled={!editable}
					error={fieldErrors[`field:${field.id}`]}
					onunreadable={(cannotRead) => (unreadable[field.id] = cannotRead)}
				/>
			</FieldShell>
		{/snippet}

		{#if globalFields.length > 0}
			<FieldGroup
				id="group-global"
				icon={Globe}
				title={m.group_global()}
				hint={m.group_global_hint()}
			>
				{#each globalFields as field (field.id)}{@render fieldShell(field)}{/each}
			</FieldGroup>
		{/if}
		{#if typeFields.length > 0 && typeName}
			<FieldGroup
				id="group-type"
				icon={Layers}
				title={m.group_type({ type: typeName })}
				hint={m.group_type_hint({ type: typeName })}
			>
				{#each typeFields as field (field.id)}{@render fieldShell(field)}{/each}
			</FieldGroup>
		{/if}
		{#if otherFields.length > 0}
			<FieldGroup
				id="group-other"
				icon={Shapes}
				title={m.group_other()}
				hint={m.group_other_hint()}
			>
				{#each otherFields as field (field.id)}{@render fieldShell(field)}{/each}
			</FieldGroup>
		{/if}

		{#if !filing}
			<FilingBox
				{document}
				{lookup}
				{viewer}
				unseen={settledUnseen}
				{editable}
				{canMove}
				{onmove}
			/>
		{/if}

		{#if reviewing && decisions.length === 0 && !failedNode && ruleNotes.length === 0 && nodeNotes.length === 0 && !hasSpace}
			<p class="px-1 text-sm text-muted-foreground">{m.review_nothing_open()}</p>
		{/if}
	</div>

	<div class="flex flex-col gap-2.5 border-t bg-card px-5 py-3.5">
		{#if formError}<p class="text-sm text-destructive" role="alert">{formError}</p>{/if}
		{#if !editable}
			<p class="text-sm text-muted-foreground">{m.edit_read_only()}</p>
		{:else if confirming}
			{#if next}
				<label class="flex items-center gap-2 text-sm text-muted-foreground">
					<input type="checkbox" bind:checked={openNext} class="size-4 accent-primary" />
					{m.review_next_document()}
				</label>
			{/if}
			{#if filingHint}
				<p
					class={cn(
						'flex items-start gap-2 text-sm',
						filingHint.tone === 'warning'
							? 'font-medium text-lane-yellow-foreground'
							: 'text-muted-foreground'
					)}
					data-testid="filing-hint"
				>
					{#if filingHint.tone === 'warning'}
						<TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
					{/if}
					<span>{filingHint.text}</span>
				</p>
			{/if}
			<div class="flex gap-2">
				<Button type="submit" disabled={busy || blocked || (filing !== null && spaceTarget === '')}
					>{m.review_confirm()}</Button
				>
				<Button type="button" variant="ghost" disabled={busy} onclick={reset}>
					{m.review_reset()}
				</Button>
			</div>
		{:else}
			<p class="text-sm text-muted-foreground">{m.edit_hint()}</p>
			<div class="flex gap-2">
				<Button type="submit" disabled={!dirty || busy || blocked}>{m.edit_review()}</Button>
				<Button type="button" variant="ghost" disabled={!dirty || busy} onclick={reset}>
					{m.edit_discard()}
				</Button>
			</div>
		{/if}
	</div>
</form>

<Dialog.Root open={preview !== null} onOpenChange={(open) => !open && (preview = null)}>
	<Dialog.Content class="sm:max-w-xl">
		<Dialog.Header>
			<Dialog.Title>{m.dryrun_title()}</Dialog.Title>
			<Dialog.Description>{m.dryrun_hint()}</Dialog.Description>
		</Dialog.Header>
		{#if preview}
			<div class="flex max-h-[60vh] flex-col gap-4 overflow-auto text-sm">
				<section>
					<h3 class="mb-1 font-medium">{m.dryrun_changes()}</h3>
					<ul class="flex flex-col gap-1">
						{#each preview.changed as field (field)}
							<li><span class="text-muted-foreground">{fieldLabel(field, lookup)}</span></li>
						{/each}
					</ul>
				</section>
				{#if preview.rules && preview.rules.length > 0}
					<section>
						<h3 class="mb-1 font-medium">{m.dryrun_rules()}</h3>
						<ul class="flex flex-col gap-2">
							{#each preview.rules as rule (rule.rule_id)}
								<li class="rounded-xl border p-3">
									<span class="font-medium">{rule.name}</span>
									<div class="mt-1">
										<RuleEffects effects={rule.applied} notes={rule.notes} {lookup} />
									</div>
								</li>
							{/each}
						</ul>
					</section>
				{/if}
				{#if preview.visibility}
					<section>
						<h3 class="mb-1 font-medium">{m.dryrun_visible()}</h3>
						<p>
							{m.dryrun_space({ space: describeValue(preview.visibility.space_id, lookup) })}
						</p>
						<p class="text-muted-foreground">
							{preview.visibility.members
								.map((member) =>
									member.role === 'read'
										? m.space_member_reads({ name: describeValue(member.user_id, lookup) })
										: describeValue(member.user_id, lookup)
								)
								.join(', ')}
						</p>
					</section>
				{/if}
			</div>
		{/if}
		<Dialog.Footer>
			<Button variant="ghost" disabled={busy} onclick={() => (preview = null)}>{m.cancel()}</Button>
			<Button disabled={busy} onclick={save}>{m.edit_save()}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
