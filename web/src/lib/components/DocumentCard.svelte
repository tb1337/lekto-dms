<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import DocumentThumb from '#lib/components/DocumentThumb.svelte';
	import InboxMark from '#lib/components/InboxMark.svelte';
	import NamesLine from '#lib/components/NamesLine.svelte';
	import TagChips from '#lib/components/TagChips.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { formatDate } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	// One document as a card of the grid: its first page, title, contact (with its logo or
	// initials) and type (with its icon) each with its shown groups, date, its shown tags, for
	// admins the owner of another user's document; on the page "in the inbox" while it stands
	// open there. `children` adds a line.
	let {
		document,
		lookup,
		href = `${BASE}/documents/${document.id}`,
		children
	}: {
		document: components['schemas']['ListedDocument'];
		lookup: Lookup | null;
		href?: string;
		children?: Snippet;
	} = $props();

	const contact = $derived(lookup?.contacts.find((entry) => entry.id === document.contact_id));
	const kind = $derived(
		lookup?.documentTypes.find((entry) => entry.id === document.document_type_id)
	);
	const owner = $derived(
		session.isAdmin && document.owner_id !== session.user?.id
			? (lookup?.users.find((user) => user.id === document.owner_id)?.username ?? null)
			: null
	);
</script>

<div
	class="relative flex h-full min-w-0 flex-col overflow-hidden rounded-2xl border bg-card transition-colors has-[>a:hover]:border-primary"
>
	<a {href} class="group flex min-w-0 flex-1 flex-col">
		<div class="aspect-[3/4] overflow-hidden border-b bg-secondary">
			<DocumentThumb id={document.id} pages={document.page_count} class="size-full" />
		</div>
		<div class="flex min-w-0 flex-1 flex-col gap-1 p-3">
			<span class="line-clamp-2 leading-snug font-medium group-hover:underline">
				{document.title}
			</span>
			<NamesLine
				parts={[{ name: contact?.name, groupIds: contact?.group_ids, avatar: contact }]}
				tags={lookup?.tags ?? []}
				class="text-sm text-muted-foreground"
			/>
			<NamesLine
				parts={[{ name: kind?.name, groupIds: kind?.group_ids, icon: kind?.icon }]}
				date={formatDate(document.document_date ?? document.created_at)}
				tags={lookup?.tags ?? []}
				class="text-xs text-muted-foreground"
			/>
			<TagChips {document} {lookup} />
			{#if owner}<Badge variant="outline" class="w-fit">{owner}</Badge>{/if}
			{@render children?.()}
		</div>
	</a>
	{#if document.in_inbox}<InboxMark lane={document.lane} class="absolute top-2 right-2" />{/if}
</div>
