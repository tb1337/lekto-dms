<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import type { CardLine } from '#lib/card-fields.ts';
	import CardFields from '#lib/components/CardFields.svelte';
	import ContactAvatar from '#lib/components/ContactAvatar.svelte';
	import DocumentThumb from '#lib/components/DocumentThumb.svelte';
	import GroupChips from '#lib/components/GroupChips.svelte';
	import InboxMark from '#lib/components/InboxMark.svelte';
	import TagChips from '#lib/components/TagChips.svelte';
	import TypeIcon from '#lib/components/TypeIcon.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { foreignSpace, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// One document as a card of the grid, "sender on top": its contact (logo or initials) in a
	// head of one line, so that the first pages of a row stand level; the first page, cut to 4:3
	// from the top, with the shown topic, tags and groups of contact and type in the upper right
	// (at most two thirds of its width) and the page count in the lower right, both as glass on
	// the image; then the title, bold, and type (with its icon) and date, all of one size.
	// "In the inbox" is a badge on the card's upper right corner while it stands open there. For
	// admins the space of a document in a space they are no member of; `children` adds a line;
	// `fields`, the fields of a lens, stand below a line.
	let {
		document,
		lookup,
		href = `${BASE}/documents/${document.id}`,
		children,
		fields = []
	}: {
		document: components['schemas']['ListedDocument'];
		lookup: Lookup | null;
		href?: string;
		children?: Snippet;
		fields?: readonly CardLine[];
	} = $props();

	const contact = $derived(lookup?.contacts.find((entry) => entry.id === document.contact_id));
	const kind = $derived(
		lookup?.documentTypes.find((entry) => entry.id === document.document_type_id)
	);
	// For admins, the space of a document in a space they are no member of.
	const foreign = $derived(foreignSpace(document.space_id, lookup, session.user?.id));
</script>

<!-- The badge stands over the card's corner: outside the card, which cuts off what overflows. -->
<div class="relative h-full min-w-0">
	<div
		class="relative flex h-full min-w-0 flex-col overflow-hidden rounded-2xl border bg-card transition-colors has-[>a:hover]:border-primary"
	>
		<a {href} class="group flex min-w-0 flex-1 flex-col text-sm">
			<div
				class={cn(
					'flex h-10 shrink-0 items-center gap-2 border-b px-3 text-muted-foreground',
					document.in_inbox && 'pr-6'
				)}
				title={contact?.name}
			>
				{#if contact}
					<ContactAvatar {contact} size="xs" />
					<span class="min-w-0 truncate">{contact.name}</span>
				{:else}
					<span class="min-w-0 truncate">{m.doc_no_contact()}</span>
				{/if}
			</div>
			<div class="relative border-b">
				<DocumentThumb id={document.id} pages={document.page_count} class="aspect-[4/3] w-full" />
				<span class="absolute top-2 right-2 flex max-w-[66%] flex-wrap justify-end gap-1">
					<TagChips {document} {lookup} onImage class="contents" />
					<GroupChips
						tags={lookup?.tags ?? []}
						ids={[...(contact?.group_ids ?? []), ...(kind?.group_ids ?? [])]}
						interactive={false}
						onImage
						class="contents"
					/>
				</span>
				{#if document.page_count}
					<span
						class="mark-glass absolute right-2 bottom-2 rounded-full bg-card/80 px-1.5 text-[0.6875rem] leading-[1.125rem] font-medium tabular-nums"
					>
						{m.doc_pages_short({ count: document.page_count })}
					</span>
				{/if}
			</div>
			<div class="flex min-w-0 flex-1 flex-col gap-1 p-3">
				<span class="line-clamp-2 leading-snug font-semibold group-hover:underline">
					{document.title}
				</span>
				<span
					class="flex min-w-0 flex-col gap-0.5 text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:gap-2"
				>
					<span class="flex min-w-0 items-center gap-1.5">
						<TypeIcon icon={kind?.icon} class="size-3.5 shrink-0" />
						<span class="truncate">{kind?.name}</span>
					</span>
					<span class="shrink-0 tabular-nums">
						{formatDate(document.document_date ?? document.created_at)}
					</span>
				</span>
				{#if foreign}<Badge variant="outline" class="w-fit">{foreign}</Badge>{/if}
				{@render children?.()}
			</div>
			{#if fields.length > 0}
				<div class="mx-3 border-t py-2.5"><CardFields lines={fields} /></div>
			{/if}
		</a>
	</div>
	{#if document.in_inbox}
		<InboxMark id={document.id} badge class="absolute -top-[7px] -right-[7px] z-10" />
	{/if}
</div>
