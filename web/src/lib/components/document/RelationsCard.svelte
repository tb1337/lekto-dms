<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import Link2 from '@lucide/svelte/icons/link-2';
	import X from '@lucide/svelte/icons/x';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import BeamTitle from '#lib/components/BeamTitle.svelte';
	import { openBeam, type BeamSource } from '#lib/beam.svelte.ts';
	import { refOf } from '#lib/fact-refs.svelte.ts';
	import ReferencePicker, {
		type Reference
	} from '#lib/components/templates/ReferencePicker.svelte';
	import { formatDate } from '#lib/i18n.ts';
	import {
		IDENTIFIER_KINDS,
		NUMBER_KINDS,
		labelOfKind,
		type IdentifierKind
	} from '#lib/identifiers.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { reportError } from '#lib/errors.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import Eyebrow from '#lib/components/page/Eyebrow.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';

	type Relations = components['schemas']['RelationsOut'];
	type Related = components['schemas']['RelatedOut'];
	const IDENTIFIER_OR_NUMBER: readonly string[] = [...IDENTIFIER_KINDS, ...NUMBER_KINDS];

	// The relations of the document (#145): the older documents it refers to, the newer ones
	// that refer to it, and Lekto's suggestions, each with what Lekto had as evidence. Who edits
	// the document relates it with another (the newer refers to the older), accepts or rejects a
	// suggestion, removes a relation, where they edit the newer of the two. A related document's
	// title opens both in the Beam, the newer first, the shared number marked in each (the eye
	// before the title says so); into the other document from there.
	let {
		documentId,
		documentTitle = '',
		lookup
	}: { documentId: string; documentTitle?: string; lookup: Lookup | null } = $props();

	let relations = $state<Relations | null>(null);
	let busy = $state(false);
	let adding = $state<Reference | null>(null);

	async function load() {
		try {
			relations = await unwrap(
				api.GET('/api/v1/documents/{id}/relations', { params: { path: { id: documentId } } })
			);
		} catch (error) {
			reportError(error);
		}
	}

	$effect(() => {
		void documentId;
		relations = null;
		void load();
	});

	async function act(call: () => Promise<Relations>, done: string) {
		busy = true;
		try {
			relations = await call();
			toast.success(done);
		} catch (error) {
			reportError(error);
			await load(); // as it is now: another may have changed it
		} finally {
			busy = false;
		}
	}

	const relate = (other: string, done: string) =>
		act(
			() =>
				unwrap(
					api.POST('/api/v1/documents/{id}/relations', {
						params: { path: { id: documentId } },
						body: { document_id: other }
					})
				),
			done
		);
	// Removing a relation asks first; rejecting a suggestion does not (web/DESIGN.md).
	let removing = $state<{ id: string; title: string } | null>(null);

	const unrelate = (other: string, done: string) =>
		act(
			() =>
				unwrap(
					api.DELETE('/api/v1/documents/{id}/relations/{other_id}', {
						params: { path: { id: documentId, other_id: other } }
					})
				),
			done
		);

	// A document picked: related at once, the picker empty again.
	$effect(() => {
		const picked = adding;
		if (!picked) return;
		adding = null;
		if (!untrack(() => busy)) void relate(picked.id, m.relations_set());
	});

	const typeName = (id: string | null | undefined) =>
		lookup?.documentTypes.find((entry) => entry.id === id)?.name ?? null;

	/** Both documents in the Beam, the newer first, the number they share marked in each. */
	async function view(item: Related, older: boolean | null) {
		const other = item.document.id;
		const ids = older === false ? [other, documentId] : [documentId, other];
		const found = item.evidence as Record<string, unknown>;
		const kind = found.fact_kind;
		const shared = (found.kind === 'fact' || found.kind === 'target') && typeof kind === 'string';
		let source: BeamSource | undefined;
		if (shared && IDENTIFIER_OR_NUMBER.includes(kind) && found.value) {
			try {
				source = {
					kind: 'fact',
					identifier: kind as IdentifierKind,
					ref: await refOf(kind as IdentifierKind, String(found.value))
				};
			} catch {
				// Without the number's reference the pages show unmarked.
			}
		}
		openBeam(ids, other, documentTitle || m.relations_title(), source ? { source } : {});
	}

	/** What Lekto had, in words; a person's relation says so. */
	function evidence(item: Related): string {
		if (item.origin === 'person') return m.relations_by_person();
		const found = item.evidence as Record<string, unknown>;
		if (found.kind === 'fact' && typeof found.fact_kind === 'string') {
			return m.relations_evidence_fact({
				kind: labelOfKind(found.fact_kind),
				value: String(found.value ?? '')
			});
		}
		if (found.kind === 'target' && typeof found.fact_kind === 'string') {
			return m.relations_evidence_target({
				kind: labelOfKind(found.fact_kind),
				value: String(found.value ?? '')
			});
		}
		if (found.kind === 'period' && typeof found.period === 'string') {
			return m.relations_evidence_period({ period: found.period });
		}
		if (found.kind === 'letter_date' && typeof found.date === 'string') {
			return m.relations_evidence_letter({ date: formatDate(found.date) });
		}
		return m.relations_by_lekto();
	}

	const groups = $derived(
		relations
			? [
					{ key: 'refers_to', title: m.relations_refers_to(), items: relations.refers_to ?? [] },
					{
						key: 'referred_by',
						title: m.relations_referred_by(),
						items: relations.referred_by ?? []
					},
					{ key: 'suggested', title: m.relations_suggested(), items: relations.suggested ?? [] }
				].filter((group) => group.items.length > 0)
			: []
	);
</script>

<Card.Root as="section" size="sm" aria-labelledby="relations-title">
	<div class="flex items-baseline gap-2 px-1 pb-1">
		<SectionTitle size="card" id="relations-title">{m.relations_title()}</SectionTitle>
		<span class="text-xs text-muted-foreground">{m.relations_hint()}</span>
	</div>
	{#if relations && groups.length === 0}
		<p class="px-1 py-2 text-sm text-muted-foreground">{m.relations_none()}</p>
	{/if}
	{#each groups as group (group.key)}
		<Eyebrow as="h3" class="mt-2 px-1">{group.title}</Eyebrow>
		{#each group.items as item (item.document.id)}
			<div class="flex items-center gap-2 rounded-xl px-2.5 py-2">
				<Link2 class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
				<div class="flex min-w-0 flex-1 flex-col gap-0.5">
					<BeamTitle
						title={item.document.title}
						class="text-sm"
						onview={() =>
							view(
								item,
								group.key === 'refers_to' ? true : group.key === 'referred_by' ? false : null
							)}
					/>
					<span class="truncate text-xs text-muted-foreground">
						{[
							typeName(item.document.document_type_id),
							item.document.document_date ? formatDate(item.document.document_date) : null
						]
							.filter(Boolean)
							.join(' · ')}
					</span>
					<span class="text-xs text-muted-foreground">{evidence(item)}</span>
				</div>
				{#if item.changeable && group.key === 'suggested'}
					<IconButton
						variant="outline"
						size="sm"
						class="shrink-0"
						disabled={busy}
						label={m.relations_accept({ title: item.document.title })}
						hint={m.relations_accept_short()}
						onclick={() => relate(item.document.id, m.relations_accepted())}
					>
						<Check aria-hidden="true" />
					</IconButton>
				{/if}
				{#if item.changeable}
					<IconButton
						size="sm"
						class="shrink-0"
						disabled={busy}
						label={group.key === 'suggested'
							? m.relations_reject({ title: item.document.title })
							: m.relations_remove({ title: item.document.title })}
						hint={group.key === 'suggested'
							? m.relations_reject_short()
							: m.relations_remove_short()}
						onclick={() =>
							group.key === 'suggested'
								? unrelate(item.document.id, m.relations_rejected())
								: (removing = item.document)}
					>
						<X aria-hidden="true" />
					</IconButton>
				{/if}
			</div>
		{/each}
	{/each}
	{#if relations?.editable}
		<div class="mt-2 px-1">
			<ReferencePicker
				bind:value={adding}
				preselect={false}
				label={m.relations_add()}
				exclude={documentId}
			/>
		</div>
	{/if}
</Card.Root>

<ConfirmDialog
	bind:open={() => removing !== null, (next) => !next && (removing = null)}
	title={m.relations_remove({ title: removing?.title ?? '' })}
	description={m.relations_remove_confirm()}
	confirmLabel={m.relations_remove_short()}
	onconfirm={async () => {
		if (removing) await unrelate(removing.id, m.relations_removed());
	}}
/>
