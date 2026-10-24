<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { m } from '#lib/paraglide/messages.js';
	import { BASE } from '#lib/base.ts';
	import { openLens } from '#lib/open-lens.svelte.ts';
	import { warmSearch } from '#lib/search-warm.ts';
	import { cn } from '#lib/utils.ts';

	// The search field of the header: Enter searches the documents with the words (and, in the
	// document view, the filters already set, and its lens, which it names); `/` jumps here from
	// anywhere but a field one types into. On a desktop the document view has no field of its
	// own: this is it.
	let { class: className = '' }: { class?: string } = $props();

	let input = $state<HTMLInputElement | null>(null);
	const DOCUMENTS = `${BASE}/documents`;
	const inDocuments = $derived(page.url.pathname === DOCUMENTS);
	// In the document view the field shows what is searched for, until the user types.
	let text = $derived(inDocuments ? (page.url.searchParams.get('q') ?? '') : '');

	function submit(event: SubmitEvent) {
		event.preventDefault();
		// Built and read at once, nothing reacts to it.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const params = new URLSearchParams(inDocuments ? page.url.search : '');
		const term = text.trim();
		if (term) params.set('q', term);
		else params.delete('q');
		params.delete('sort'); // a search sorts as the last search did
		const query = params.toString();
		void goto(query ? `${DOCUMENTS}?${query}` : DOCUMENTS);
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

<form
	role="search"
	onsubmit={submit}
	class={cn(
		'flex h-10 items-center gap-2 rounded-full border border-input bg-background pr-1.5 pl-3.5 focus-within:border-ring',
		className
	)}
>
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
		class="rounded-md border bg-card px-1.5 font-mono text-[11px] leading-5 text-muted-foreground"
		aria-hidden="true">/</kbd
	>
</form>
