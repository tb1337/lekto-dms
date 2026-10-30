<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import { page } from '$app/state';
	import { m } from '#lib/paraglide/messages.js';
	import { BASE } from '#lib/base.ts';
	import { openLens } from '#lib/open-lens.svelte.ts';
	import { warmSearch } from '#lib/meaning-search.ts';
	import { cn } from '#lib/utils.ts';
	import { gotoSearching, stateWords } from '#lib/words.ts';
	import { FIELD_FRAME } from '#lib/components/ui/field-look.ts';

	// The search field of the header: Enter searches the documents with the words (and, in the
	// document view, the filters already set, and its lens, which it names); `/` jumps here from
	// anywhere but a field one types into. On a desktop the document view has no field of its
	// own: this is it.
	let { class: className = '' }: { class?: string } = $props();

	let input = $state<HTMLInputElement | null>(null);
	const DOCUMENTS = `${BASE}/documents`;
	const inDocuments = $derived(page.url.pathname === DOCUMENTS);
	// In the document view the field shows what is searched for, until the user types: the
	// words of the history entry, or those of the lens a plain link opened (`lib/words.ts`).
	let text = $derived(inDocuments ? (stateWords(page.state) ?? openLens.query ?? '') : '');

	function submit(event: SubmitEvent) {
		event.preventDefault();
		// Built and read at once, nothing reacts to it.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const params = new URLSearchParams(inDocuments ? page.url.search : '');
		params.delete('sort'); // a search sorts as the last search did
		const query = params.toString();
		// The words go into the history entry, never into the address.
		void gotoSearching(query ? `${DOCUMENTS}?${query}` : DOCUMENTS, text.trim());
	}

	function keydown(event: KeyboardEvent) {
		if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
		const target = event.target as HTMLElement | null;
		const typing =
			target !== null &&
			(target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
		if (typing) return;
		event.preventDefault();
		input?.focus();
	}
</script>

<svelte:window onkeydown={keydown} />

<form role="search" onsubmit={submit} class={cn(FIELD_FRAME, 'h-10 pr-1.5 pl-3.5', className)}>
	<SearchIcon class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
	<input
		bind:this={input}
		bind:value={text}
		type="search"
		aria-label={m.header_search_label()}
		placeholder={inDocuments && openLens.name
			? m.header_search_in({ name: openLens.name })
			: m.header_search_placeholder()}
		oninput={() => warmSearch()}
		class="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
	/>
	<kbd
		class="rounded-md border bg-card px-1.5 font-mono text-micro leading-5 text-muted-foreground"
		aria-hidden="true">/</kbd
	>
</form>
