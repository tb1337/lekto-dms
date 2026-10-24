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

	// One document in a list: preview, title, contact (with its logo or initials) and type
	// (with its icon) each with its shown groups, date, its shown tags, for admins the space of
	// a document in a space they are no member of. `children` adds a line, `fields` the fields of a lens;
	// `aside` stands at the end of the row, beside its link (a button, a link of its own).
	let {
		document,
		lookup,
		href = `${BASE}/documents/${document.id}`,
		children,
		fields = [],
		aside
	}: {
		document: components['schemas']['DocumentDetails'];
		lookup: Lookup | null;
		href?: string;
		children?: Snippet;
		fields?: readonly CardLine[];
		aside?: Snippet;
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

<div
	class="flex items-center gap-3 rounded-2xl border bg-card p-3 transition-colors has-[>a:hover]:border-primary"
>
	<a {href} class="flex min-w-0 flex-1 items-center gap-4 rounded-lg">
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
	</a>
	{@render aside?.()}
</div>
