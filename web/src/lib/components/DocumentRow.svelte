<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import type { CardLine } from '#lib/card-fields.ts';
	import CardFields from '#lib/components/CardFields.svelte';
	import DocumentThumb from '#lib/components/DocumentThumb.svelte';
	import NamesLine from '#lib/components/NamesLine.svelte';
	import TagChips from '#lib/components/TagChips.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { byId, foreignSpace, type Lookup } from '#lib/masterdata.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import { ChoiceBox } from '#lib/components/ui/choice/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// One document in a list: preview, title, contact (with its logo or initials) and type
	// (with its icon) each with its shown groups, date, its shown tags, for admins the space of
	// a document in a space they are no member of. `children` adds a line, `fields` the fields of a lens;
	// `aside` stands at the end of the row, beside its link (a button, a link of its own). With
	// `onchoose` (the selection mode of the list) the row is no link but the label of its box,
	// which starts it: a tap chooses it; a chosen row has `bg-panel` and a primary edge.
	let {
		document,
		lookup,
		href = `${BASE}/documents/${document.id}`,
		children,
		fields = [],
		aside,
		chosen = false,
		onchoose
	}: {
		document: components['schemas']['DocumentDetails'];
		lookup: Lookup | null;
		href?: string;
		children?: Snippet;
		fields?: readonly CardLine[];
		aside?: Snippet;
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
	// For admins, the space of a document in a space they are no member of.
	const foreign = $derived(foreignSpace(document.space_id, lookup, session.user?.id));
</script>

<Card.Root
	size="flush"
	class={cn(
		'flex items-center gap-3 p-3 transition-colors has-[>a:hover]:border-primary has-[>label:hover]:border-primary',
		chosen && 'border-primary bg-panel'
	)}
>
	<svelte:element
		this={onchoose ? 'label' : 'a'}
		href={onchoose ? undefined : href}
		class={cn('flex min-w-0 flex-1 items-center gap-4 rounded-lg', onchoose && 'cursor-pointer')}
	>
		{#if onchoose}
			<ChoiceBox
				checked={chosen}
				aria-label={m.bulk_select_document({ title: document.title })}
				onchange={(event) => onchoose(event.currentTarget.checked)}
			/>
		{/if}
		<DocumentThumb
			id={document.id}
			pages={document.page_count}
			class="h-20 w-14 shrink-0 rounded-lg border"
		/>
		<div class="flex min-w-0 flex-1 flex-col gap-1">
			<span class="flex min-w-0 items-center gap-2">
				<span class="truncate font-medium">{document.title}</span>
				{#if foreign}<Badge variant="outline" class="shrink-0">{foreign}</Badge>{/if}
			</span>
			<NamesLine
				parts={[
					{ name: contact?.name, groupIds: contact?.group_ids, avatar: contact },
					{ name: kind?.name, groupIds: kind?.group_ids, icon: kind?.icon }
				]}
				date={formatDate(document.document_date ?? document.created_at)}
				tags={lookup?.tags ?? []}
				class="text-sm text-muted-foreground"
			/>
			<TagChips {document} {lookup} />
			{@render children?.()}
			{#if fields.length > 0}<div class="max-w-sm"><CardFields lines={fields} /></div>{/if}
		</div>
	</svelte:element>
	{@render aside?.()}
</Card.Root>
