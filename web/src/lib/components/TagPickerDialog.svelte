<script lang="ts">
	import type { Snippet } from 'svelte';
	import PhoneSheet from '#lib/components/PhoneSheet.svelte';
	import TagPickerList from '#lib/components/TagPickerList.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';

	// Several tags of one scope, chosen in a dialog over the page or editor it is opened from (on
	// a phone a sheet from the bottom, `PhoneSheet`), the list of `TagPickerList`.
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
{#snippet done()}
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
{/snippet}

{#snippet list()}
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
{/snippet}

{#if phone.current}
	<PhoneSheet bind:open {title} onOpenChange={(value) => !value && (query = '')} close={done}>
		{@render list()}
	</PhoneSheet>
{:else}
	<Dialog.Root bind:open onOpenChange={(value) => !value && (query = '')}>
		<!-- Wider screens start in the search. -->
		<Dialog.Content
			size="md"
			showCloseButton={false}
			onOpenAutoFocus={(event) => {
				event.preventDefault();
				search?.focus();
			}}
			class="flex h-[min(36rem,calc(100dvh-2rem))] flex-col gap-0 overflow-hidden p-0"
		>
			<div class="flex shrink-0 items-center justify-between gap-2 py-2 pr-2 pl-4">
				<Dialog.Title class="text-base font-semibold">{title}</Dialog.Title>
				{@render done()}
			</div>
			{@render list()}
		</Dialog.Content>
	</Dialog.Root>
{/if}
