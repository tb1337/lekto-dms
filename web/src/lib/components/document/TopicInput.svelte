<script lang="ts">
	import SearchSelect from '#lib/components/SearchSelect.svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import type { Tag } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { createQuickly, createWithDetails } from '#lib/tag-create.ts';
	import { pathLabel } from '#lib/tags.ts';

	// The topic of a document, or none (`SearchSelect`): the chosen one as its chip, a search
	// over `topics` (the ones that may be chosen; the search finds a topic by the name of one
	// above it too). Where `creating` (an admin, with a contact), a search that finds no topic
	// named so offers to create one (`tag-create.ts`), chosen at once; `oncreated` tells the
	// form.
	let {
		value = $bindable(''),
		topics,
		all,
		id,
		disabled = false,
		placeholder,
		creating = false,
		oncreated = () => {}
	}: {
		value?: string;
		topics: readonly Tag[];
		/** Every tag: a topic of another contact counts as named already. */
		all: readonly Tag[];
		id: string;
		disabled?: boolean;
		/** What the field says without a topic. */
		placeholder: string;
		creating?: boolean;
		oncreated?: (tag: Tag) => void;
	} = $props();

	// Topics made here, until `all` and `topics` hold them too.
	let made = $state<Tag[]>([]);
	const known = $derived([
		...all,
		...made.filter((tag) => !all.some((other) => other.id === tag.id))
	]);
	const options = $derived(
		topics.map((tag) => ({
			value: tag.id,
			label: tag.name,
			hint: tag.path.length > 1 ? pathLabel(tag) : undefined
		}))
	);

	function option(tag: Tag) {
		made = [...made, tag];
		oncreated(tag);
		return { value: tag.id, label: tag.name };
	}

	async function quick(name: string) {
		const tag = await createQuickly('topic', name);
		return tag ? option(tag) : null;
	}

	async function withDetails(name: string) {
		const tag = await createWithDetails('topic', name);
		return tag ? option(tag) : null;
	}
</script>

<SearchSelect
	{id}
	bind:value
	{disabled}
	{placeholder}
	{options}
	noneLabel={m.topic_none()}
	searchLabel={creating ? m.picker_search_create() : m.assignment_search()}
	create={creating ? quick : undefined}
	details={creating ? withDetails : undefined}
>
	{#snippet chosen(entry)}
		{@const tag = known.find((candidate) => candidate.id === entry.value)}
		{#if tag}
			<TagChip {tag} topic size="sm" />
		{:else}
			<span class="min-w-0 flex-1 truncate">{entry.label}</span>
		{/if}
	{/snippet}
</SearchSelect>
