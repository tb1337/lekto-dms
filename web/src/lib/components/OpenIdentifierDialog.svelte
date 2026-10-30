<script lang="ts">
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { BASE } from '#lib/base.ts';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import Eyebrow from '#lib/components/page/Eyebrow.svelte';
	import FormDialog from '#lib/components/FormDialog.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Mark from '#lib/components/Mark.svelte';
	import Select from '#lib/components/Select.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { roleLabel, shown } from '#lib/facts.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { kindLabel } from '#lib/identifiers.ts';
	import {
		decideOne,
		type OpenAction,
		type OpenDetail,
		type OpenIdentifier,
		targetName
	} from '#lib/open-identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { reasonText } from '#lib/reasons.ts';

	// An open identifier opened from the list (web/DESIGN.md, "Lists": the title opens it):
	// where it is open, where it stands in its newest documents (the text around it, the value
	// marked), and the decision. A learned one is decided at its contact; for an unknown one the
	// person picks among the contacts of its documents; a suggestion names its contact or the
	// person whose profile takes it. "Übernehmen" is the primary action, "Verwerfen" the second
	// way out at the start of the footer.
	let {
		open = $bindable(false),
		item,
		ondecided
	}: {
		open?: boolean;
		item: OpenIdentifier | null;
		ondecided: (action: OpenAction) => void;
	} = $props();

	let detail = $state<OpenDetail | null>(null);
	let problem = $state<string | null>(null);
	let contact = $state('');

	async function load(wanted: OpenIdentifier) {
		detail = null;
		problem = null;
		try {
			const found = await unwrap(
				api.GET('/api/v1/identifiers/open/{kind}/{ref}', {
					params: { path: { kind: wanted.kind, ref: wanted.ref } }
				})
			);
			if (item === wanted) detail = found;
		} catch (error) {
			if (item === wanted) problem = describeError(error);
		}
	}

	$effect(() => {
		if (!open || !item) return;
		contact = item.contacts[0]?.id ?? '';
		void load(item);
	});

	const title = $derived(item ? `${kindLabel(item.kind)} ${shown(item)}` : '');
	const description = $derived.by(() => {
		if (!item) return '';
		const count = formatNumber(item.documents);
		if (item.source === 'learned') {
			return m.open_learned_at({ contact: item.contacts[0]?.name ?? '', count });
		}
		if (item.source === 'suggested') {
			const one = item.documents === 1;
			if (item.person) {
				const person = item.person.name;
				return one
					? m.open_suggested_person_one({ person })
					: m.open_suggested_person({ person, count });
			}
			const contact = targetName(item);
			return one
				? m.open_suggested_contact_one({ contact })
				: m.open_suggested_contact({ contact, count });
		}
		return item.documents === 1 ? m.open_unknown_in_one() : m.open_unknown_in({ count });
	});

	// On a phone the bar on top keeps room for the title: the verb alone, the text names whose.
	const submitLabel = $derived.by(() => {
		if (item?.source !== 'suggested' || phone.current) return m.open_confirm();
		return item.person
			? m.open_confirm_profile({ person: item.person.name })
			: m.open_confirm_at({ contact: targetName(item) });
	});

	const hint = $derived.by(() => {
		if (!item) return '';
		if (item.source === 'learned') return m.open_dialog_hint_learned();
		if (item.source === 'unknown') return m.open_dialog_hint_unknown();
		return item.person
			? m.open_dialog_hint_suggested_person()
			: m.open_dialog_hint_suggested_contact();
	});

	async function run(action: OpenAction) {
		if (!item) return;
		await decideOne({
			kind: item.kind,
			value: item.value,
			action,
			contact_id: item.source === 'unknown' && contact ? contact : null
		});
		ondecided(action);
	}
</script>

<FormDialog
	bind:open
	{title}
	{description}
	{submitLabel}
	disabled={!item}
	action={() => run('confirm')}
	alternative={{ label: m.open_reject(), action: () => run('reject') }}
>
	{#if item}
		{#if item.recommendation}
			<p class="flex flex-wrap items-center gap-2 text-meta">
				<Badge variant={item.recommendation.action === 'confirm' ? 'green' : 'muted'}>
					{item.recommendation.action === 'confirm'
						? m.open_advise_confirm()
						: m.open_advise_reject()}
				</Badge>
				<span class="text-muted-foreground">{reasonText(item.recommendation.reason)}</span>
			</p>
		{/if}
		{#if item.source === 'unknown' && item.contacts.length > 1}
			<Field.Field>
				<Field.Label for="open-contact">{m.open_contact_label()}</Field.Label>
				<Select
					id="open-contact"
					bind:value={contact}
					options={item.contacts.map((entry) => ({ value: entry.id, label: entry.name }))}
				/>
			</Field.Field>
		{/if}
		<div class="flex flex-col gap-2">
			<Eyebrow>{m.open_places()}</Eyebrow>
			{#if problem}
				<LoadProblem {problem} onretry={() => item && load(item)} />
			{:else if !detail}
				<Loading />
			{:else if detail.places.length === 0}
				<EmptyNote compact>{m.open_places_none()}</EmptyNote>
			{:else}
				<ul class="flex flex-col gap-2">
					{#each detail.places as place (place.document_id)}
						<Card.Root as="li" size="sm" class="flex flex-col gap-2">
							<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
								<a
									class="inline-flex min-h-6 min-w-0 flex-1 items-center font-medium text-brand hover:underline max-sm:min-h-11"
									href={`${BASE}/documents/${place.document_id}`}>{place.title}</a
								>
								<span class="text-meta text-muted-foreground tabular-nums">
									{formatDate(place.date)}
								</span>
								<Badge variant="note">{roleLabel(place.role)}</Badge>
							</div>
							{#if place.excerpt}
								<p class="rounded-xl bg-surface px-3 py-2 text-meta break-words">
									{place.excerpt.before}<Mark>{place.excerpt.match}</Mark>{place.excerpt.after}
								</p>
							{:else}
								<p class="text-meta text-muted-foreground">{m.open_place_no_text()}</p>
							{/if}
						</Card.Root>
					{/each}
				</ul>
			{/if}
		</div>
		<p class="text-meta text-muted-foreground">{hint}</p>
	{/if}
</FormDialog>
