<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import Link2 from '@lucide/svelte/icons/link-2';
	import X from '@lucide/svelte/icons/x';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { documentHref } from '#lib/candidates.ts';
	import ReferencePicker, {
		type Reference
	} from '#lib/components/templates/ReferencePicker.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { kindLabel, type IdentifierKind } from '#lib/identifiers.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { reportError } from '#lib/errors.ts';

	type Relations = components['schemas']['RelationsOut'];
	type Related = components['schemas']['RelatedOut'];

	// The relations of the document (#145): the older documents it refers to, the newer ones
	// that refer to it, and Lekto's suggestions, each with what Lekto had as evidence. Who edits
	// the document relates it with another (the newer refers to the older), accepts or rejects a
	// suggestion, removes a relation, where they edit the newer of the two.
	let { documentId, lookup }: { documentId: string; lookup: Lookup | null } = $props();

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
		void relate(picked.id, m.relations_set());
	});

	const typeName = (id: string | null | undefined) =>
		lookup?.documentTypes.find((entry) => entry.id === id)?.name ?? null;

	/** What Lekto had, in words; a person's relation says so. */
	function evidence(item: Related): string {
		if (item.origin === 'person') return m.relations_by_person();
		const found = item.evidence as Record<string, unknown>;
		if (found.kind === 'fact' && typeof found.fact_kind === 'string') {
			return m.relations_evidence_fact({
				kind: kindLabel(found.fact_kind as IdentifierKind),
				value: String(found.value ?? '')
			});
		}
		if (found.kind === 'period' && typeof found.period === 'string') {
			return m.relations_evidence_period({ period: found.period });
		}
		return m.relations_by_lekto();
	}

	const groups = $derived(
		relations
			? [
					{ key: 'refers_to', title: m.relations_refers_to(), items: relations.refers_to },
					{ key: 'referred_by', title: m.relations_referred_by(), items: relations.referred_by },
					{ key: 'suggested', title: m.relations_suggested(), items: relations.suggested }
				].filter((group) => group.items.length > 0)
			: []
	);
</script>

<section aria-labelledby="relations-title" class="rounded-2xl border bg-card p-3.5">
	<div class="flex items-baseline gap-2 px-1 pb-1">
		<h2 id="relations-title" class="text-[15px] font-semibold">{m.relations_title()}</h2>
		<span class="text-xs text-muted-foreground">{m.relations_hint()}</span>
	</div>
	{#if relations && groups.length === 0}
		<p class="px-1 py-2 text-sm text-muted-foreground">{m.relations_none()}</p>
	{/if}
	{#each groups as group (group.key)}
		<h3 class="mt-2 px-1 text-xs font-semibold text-muted-foreground">{group.title}</h3>
		{#each group.items as item (item.document.id)}
			<div class="flex items-center gap-2 rounded-xl px-2.5 py-2">
				<Link2 class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
				<div class="flex min-w-0 flex-1 flex-col gap-0.5">
					<a
						href={documentHref(item.document.id)}
						class="truncate text-sm font-medium underline-offset-2 hover:underline"
						>{item.document.title}</a
					>
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
					<Button
						variant="outline"
						size="icon"
						class="size-8 shrink-0"
						disabled={busy}
						aria-label={m.relations_accept({ title: item.document.title })}
						title={m.relations_accept_short()}
						onclick={() => relate(item.document.id, m.relations_accepted())}
					>
						<Check aria-hidden="true" />
					</Button>
				{/if}
				{#if item.changeable}
					<Button
						variant="ghost"
						size="icon"
						class="size-8 shrink-0"
						disabled={busy}
						aria-label={m.relations_remove({ title: item.document.title })}
						title={group.key === 'suggested'
							? m.relations_reject_short()
							: m.relations_remove_short()}
						onclick={() => unrelate(item.document.id, m.relations_removed())}
					>
						<X aria-hidden="true" />
					</Button>
				{/if}
			</div>
		{/each}
	{/each}
	{#if relations?.editable}
		<div class="mt-2 px-1">
			<ReferencePicker bind:value={adding} preselect={false} label={m.relations_add()} />
		</div>
	{/if}
</section>
