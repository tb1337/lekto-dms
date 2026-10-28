<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import type { CardLine } from '#lib/card-fields.ts';
	import CardFields from '#lib/components/CardFields.svelte';
	import ContactAvatar from '#lib/components/ContactAvatar.svelte';
	import DocumentThumb from '#lib/components/DocumentThumb.svelte';
	import InboxMark from '#lib/components/InboxMark.svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import { shownChips } from '#lib/tags.ts';
	import TypeIcon from '#lib/components/TypeIcon.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { byId, foreignSpace, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import { ChoiceBox } from '#lib/components/ui/choice/index.ts';

	// One document as a card of the grid, "sender on top" (web/DESIGN.md, "Document card"): its
	// contact (logo or initials) in a head of one line, so that the first pages of a row stand
	// level, with "in the inbox" at its end while it stands open there; the first page, cut to
	// 4:3 from the top, with only the page count on it (as glass); then the title, bold, type
	// (with its icon) and date, and the shown topic, tags and groups of contact and type in one
	// line, "+n" for the rest. For admins the space of a document in a space they are no member
	// of; `children` adds a line; `fields`, the fields of a lens, stand below a line. With
	// `onchoose` (the selection mode of the list) the card is no link but the label of its box,
	// which starts its head: a tap chooses it; a chosen card has `bg-panel` and a primary edge.
	let {
		document,
		lookup,
		href = `${BASE}/documents/${document.id}`,
		children,
		fields = [],
		chosen = false,
		onchoose
	}: {
		document: components['schemas']['ListedDocument'];
		lookup: Lookup | null;
		href?: string;
		children?: Snippet;
		fields?: readonly CardLine[];
		chosen?: boolean;
		onchoose?: (chosen: boolean) => void;
	} = $props();

	// By the indexes of the lists: one card of many must not scan them on every render.
	const contact = $derived(
		lookup && document.contact_id ? byId(lookup.contacts).get(document.contact_id) : undefined
	);
	const kind = $derived(
		lookup && document.document_type_id
			? byId(lookup.documentTypes).get(document.document_type_id)
			: undefined
	);
	// The topic first, then the tags, then the groups of contact and type; three fit a line.
	const chips = $derived.by(() => {
		if (!lookup) return [];
		const topic = document.topic_id ? shownChips(lookup.tags, [document.topic_id]) : [];
		const groups = shownChips(lookup.tags, [
			...(contact?.group_ids ?? []),
			...(kind?.group_ids ?? [])
		]);
		return [
			...topic.map((tag) => ({ tag, look: 'topic' as const })),
			...shownChips(lookup.tags, document.tag_ids).map((tag) => ({ tag, look: 'tag' as const })),
			...groups.map((tag) => ({ tag, look: 'group' as const }))
		];
	});
	const FITS = 3;
	const rest = $derived(chips.slice(FITS));
	// For admins, the space of a document in a space they are no member of.
	const foreign = $derived(foreignSpace(document.space_id, lookup, session.user?.id));
</script>

<!-- The inbox mark is a link of its own: it stands over the card's link, not inside it. -->
<div class="relative h-full min-w-0">
	<Card.Root
		size="flush"
		class={cn(
			'relative flex h-full min-w-0 flex-col overflow-hidden transition-colors has-[>a:hover]:border-primary has-[>label:hover]:border-primary',
			chosen && 'border-primary bg-panel'
		)}
	>
		<svelte:element
			this={onchoose ? 'label' : 'a'}
			href={onchoose ? undefined : href}
			class={cn('group flex min-w-0 flex-1 flex-col text-sm', onchoose && 'cursor-pointer')}
		>
			<div
				class={cn(
					'flex h-10 shrink-0 items-center gap-2 border-b px-3 text-muted-foreground',
					document.in_inbox && 'pr-11'
				)}
				title={contact?.name}
			>
				{#if onchoose}
					<ChoiceBox
						checked={chosen}
						aria-label={m.bulk_select_document({ title: document.title })}
						onchange={(event) => onchoose(event.currentTarget.checked)}
					/>
				{/if}
				{#if contact}
					<ContactAvatar {contact} size="xs" />
					<span class="min-w-0 truncate">{contact.name}</span>
				{:else}
					<span class="min-w-0 truncate">{m.doc_no_contact()}</span>
				{/if}
			</div>
			<div class="relative border-b">
				<DocumentThumb id={document.id} pages={document.page_count} class="aspect-[4/3] w-full" />
				{#if document.page_count}
					<span
						class="mark-glass absolute right-2 bottom-2 rounded-full bg-card/80 px-1.5 text-micro leading-[1.125rem] font-medium tabular-nums"
					>
						{m.doc_pages_short({ count: document.page_count })}
					</span>
				{/if}
			</div>
			<div class="flex min-w-0 flex-1 flex-col gap-1 p-3">
				<span
					class={cn(
						'line-clamp-2 leading-snug font-semibold break-words hyphens-auto',
						!onchoose && 'group-hover:underline'
					)}
				>
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
				{#if chips.length > 0}
					<span class="mt-1 flex min-w-0 items-center gap-1 overflow-hidden">
						{#each chips.slice(0, FITS) as chip (chip.tag.id)}
							<TagChip
								tag={chip.tag}
								topic={chip.look === 'topic'}
								group={chip.look === 'group'}
								size="sm"
							/>
						{/each}
						{#if rest.length > 0}
							<!-- The names of the rest, cut off here, on hover. -->
							<Badge
								variant="muted"
								class="shrink-0"
								title={rest.map((chip) => chip.tag.name).join(', ')}>+{rest.length}</Badge
							>
						{/if}
					</span>
				{/if}
				{#if foreign}<Badge variant="outline" class="w-fit">{foreign}</Badge>{/if}
				{@render children?.()}
			</div>
			{#if fields.length > 0}
				<div class="mx-3 border-t py-2.5"><CardFields lines={fields} /></div>
			{/if}
		</svelte:element>
	</Card.Root>
	{#if document.in_inbox}
		<InboxMark id={document.id} badge class="absolute top-2 right-2 z-10" />
	{/if}
</div>
