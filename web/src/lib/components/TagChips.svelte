<script lang="ts">
	import TagChip from '#lib/components/TagChip.svelte';
	import type { Contact, DocumentType, Lookup } from '#lib/masterdata.svelte.ts';
	import { shownChips } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The chips of a document: the shown groups of its contact and type (outlined) and its
	// shown tags, each by its own name with the path as tooltip.
	let {
		document,
		lookup,
		interactive = false,
		size = 'sm',
		class: className
	}: {
		document: {
			tag_ids: readonly string[];
			contact_id?: string | null;
			document_type_id?: string | null;
		};
		lookup: Lookup | null;
		interactive?: boolean;
		size?: 'sm' | 'md';
		class?: string;
	} = $props();

	const tags = $derived(lookup ? shownChips(lookup.tags, document.tag_ids) : []);
	const groups = $derived.by(() => {
		if (!lookup) return [];
		const contact: Contact | undefined = lookup.contacts.find(
			(entry) => entry.id === document.contact_id
		);
		const kind: DocumentType | undefined = lookup.documentTypes.find(
			(entry) => entry.id === document.document_type_id
		);
		return shownChips(lookup.tags, [...(contact?.group_ids ?? []), ...(kind?.group_ids ?? [])]);
	});
</script>

{#if tags.length > 0 || groups.length > 0}
	<span class={cn('flex min-w-0 flex-wrap gap-1', className)}>
		{#each groups as tag (tag.id)}<TagChip {tag} group {interactive} {size} />{/each}
		{#each tags as tag (tag.id)}<TagChip {tag} {interactive} {size} />{/each}
	</span>
{/if}
