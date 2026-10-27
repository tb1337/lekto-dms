<script lang="ts">
	import type { Snippet } from 'svelte';
	import TagPickerList from '#lib/components/TagPickerList.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// Several tags of one scope, chosen in a dialog over the page or editor it is opened from (on
	// a phone a sheet from the bottom), the list of `TagPickerList`.
	let {
		open = $bindable(false),
		title,
		scope,
		tags,
		selected,
		onchange,
		query = $bindable(''),
		searchLabel = m.assignment_search(),
		offered,
		actions
	}: {
		open?: boolean;
		title: string;
		scope: TagScope;
		tags: readonly Tag[];
		selected: readonly string[];
		onchange: (selected: string[]) => void;
		query?: string;
		searchLabel?: string;
		offered?: (tag: Tag) => boolean;
		actions?: Snippet;
	} = $props();

	let search = $state<HTMLInputElement | null>(null);
</script>

<!-- However it closes, the next time it opens with an empty search: bits-ui reports only its own
     closes (Escape, outside), "Fertig" clears it itself. -->
<Dialog.Root bind:open onOpenChange={(value) => !value && (query = '')}>
	<Dialog.Content
		size="md"
		showCloseButton={false}
		onOpenAutoFocus={(event) => {
			// Wider screens start in the search; a phone's keyboard waits for a tap.
			if (phone.current) return;
			event.preventDefault();
			search?.focus();
		}}
		class={cn(
			'flex flex-col gap-0 overflow-hidden p-0',
			phone.current
				? 'top-auto bottom-0 left-0 h-[85dvh] max-h-[85dvh] w-full max-w-none translate-x-0 translate-y-0 rounded-t-2xl rounded-b-none data-[state=open]:slide-in-from-bottom-10'
				: 'h-[min(36rem,calc(100dvh-2rem))]'
		)}
	>
		{#if phone.current}
			<span class="mx-auto mt-2 h-1.5 w-10 shrink-0 rounded-full bg-border" aria-hidden="true"
			></span>
		{/if}
		<div class="flex shrink-0 items-center justify-between gap-2 py-2 pr-2 pl-4">
			<Dialog.Title class="text-base font-semibold">{title}</Dialog.Title>
			<Button
				variant="ghost"
				class="h-11 px-3 text-base font-semibold text-brand"
				onclick={() => {
					query = '';
					open = false;
				}}
			>
				{m.picker_done()}
			</Button>
		</div>
		<TagPickerList
			{title}
			{scope}
			{tags}
			{selected}
			{onchange}
			{offered}
			{searchLabel}
			bind:query
			bind:search
			{actions}
		/>
	</Dialog.Content>
</Dialog.Root>
