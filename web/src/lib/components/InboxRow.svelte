<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import CheckCheck from '@lucide/svelte/icons/check-check';
	import Eye from '@lucide/svelte/icons/eye';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import DocumentRow from '#lib/components/DocumentRow.svelte';
	import LaneBadge from '#lib/components/LaneBadge.svelte';
	import ProcessingProgress from '#lib/components/ProcessingProgress.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { inboxDocument } from '#lib/document-view.ts';
	import { formatDate } from '#lib/i18n.ts';
	import type { InboxItem } from '#lib/inbox-view.ts';
	import { byId, userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { labelled, reasonsText } from '#lib/reasons.ts';
	import { session } from '#lib/session.svelte.ts';
	import { onlySpace, suggestedSpace, suggestionText } from '#lib/space-suggestion.ts';

	// One document of the inbox, by where it stands: in processing with its progress; yellow or
	// red with its lane and why (a suggested space as the suggestion); new calmly, marked and
	// with "seen" (no call to act); done with how, when and by whom, and "new again" for one
	// seen. The actions stand beside the row's link; on a phone as icons a finger can hit.
	let {
		item,
		lookup,
		busy = false,
		onseen,
		onunseen
	}: {
		item: InboxItem;
		lookup: Lookup | null;
		/** An action of this row is running. */
		busy?: boolean;
		onseen: (id: string) => void;
		onunseen: (id: string) => void;
	} = $props();

	const document = $derived(item.document);
	const done = $derived(item.done);
	const who = $derived.by(() => {
		if (!done) return '';
		if (done.by === session.user?.id) return m.inbox_by_you();
		const user = lookup ? byId(lookup.users).get(done.by) : undefined;
		return user ? userLabel(user) : m.inbox_by_unknown();
	});
	const when = $derived(
		done ? formatDate(done.at, { dateStyle: 'medium', timeStyle: 'short' }) : ''
	);
	// Waiting only for the space Lekto suggests: say which, and who would see it there.
	const suggestion = $derived(onlySpace(item.open) ? suggestedSpace(item.open) : null);
	const action = 'h-11 shrink-0 max-sm:w-11 max-sm:px-0 sm:h-9';
</script>

<DocumentRow {document} {lookup} href={inboxDocument(document.id)}>
	{#if item.tab === 'processing'}
		<ProcessingProgress processing={document.processing} compact class="mt-1 max-w-48" />
	{:else if item.tab === 'review' || item.tab === 'intervene'}
		<!-- On a phone the reason gets a line of its own, two at most, instead of a few words. -->
		<span
			class="flex min-w-0 flex-col items-start gap-1 text-sm sm:flex-row sm:items-center sm:gap-2"
		>
			<LaneBadge lane={document.lane} class="shrink-0" />
			<span class="line-clamp-2 text-muted-foreground sm:line-clamp-1">
				{suggestion
					? suggestionText(suggestion, document.space_id, lookup)
					: (reasonsText(item.open[0]?.reasons, item.open[0]?.reason, labelled(lookup)) ??
						m.inbox_open_fields({ count: item.open.length }))}
			</span>
		</span>
	{:else if item.tab === 'new'}
		<span class="flex items-center gap-1.5 text-sm font-medium text-brand">
			<span class="size-2 rounded-full bg-primary" aria-hidden="true"></span>
			{m.inbox_new()}
		</span>
	{:else if done}
		<span class="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
			{#if done.how === 'confirmed'}
				<CheckCheck class="size-4 shrink-0" aria-hidden="true" />
				<span class="truncate">{m.inbox_done_confirmed({ who, when })}</span>
			{:else}
				<Eye class="size-4 shrink-0" aria-hidden="true" />
				<span class="truncate">{m.inbox_done_seen({ who, when })}</span>
			{/if}
		</span>
	{/if}
	{#snippet aside()}
		{#if item.tab === 'new'}
			<Button variant="outline" class={action} disabled={busy} onclick={() => onseen(document.id)}>
				<Check aria-hidden="true" />
				<span class="max-sm:sr-only">{m.inbox_seen()}</span>
			</Button>
		{:else if done?.how === 'seen'}
			<Button variant="ghost" class={action} disabled={busy} onclick={() => onunseen(document.id)}>
				<Undo2 aria-hidden="true" />
				<span class="max-sm:sr-only">{m.inbox_unseen()}</span>
			</Button>
		{/if}
	{/snippet}
</DocumentRow>
