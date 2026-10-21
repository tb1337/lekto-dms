<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import type { FacetItem } from '#lib/components/FacetList.svelte';
	import TypeIcon from '#lib/components/TypeIcon.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// Every value of a group of the filters, to search and choose from: by name, under their
	// first letter, each with its count and what it belongs to (`hint`). Choices apply at once.
	let {
		open = $bindable(false),
		title,
		searchLabel,
		items,
		selected,
		onchange
	}: {
		open?: boolean;
		title: string;
		searchLabel: string;
		items: readonly FacetItem[];
		selected: readonly string[];
		onchange: (next: string[]) => void;
	} = $props();

	let query = $state('');
	const sections = $derived.by(() => {
		const words = query.trim().toLocaleLowerCase();
		const found = items
			.filter((item) => !words || item.label.toLocaleLowerCase().includes(words))
			.toSorted((a, b) => a.label.localeCompare(b.label));
		const byLetter: { letter: string; items: FacetItem[] }[] = [];
		for (const item of found) {
			const letter = item.label.charAt(0).toLocaleUpperCase();
			const last = byLetter.at(-1);
			if (last?.letter === letter) last.items.push(item);
			else byLetter.push({ letter, items: [item] });
		}
		return byLetter;
	});

	function toggle(id: string, checked: boolean) {
		onchange(checked ? [...selected, id] : selected.filter((entry) => entry !== id));
	}
</script>

<Dialog.Root bind:open onOpenChange={(next) => next || (query = '')}>
	<Dialog.Content class="flex max-h-[85dvh] flex-col gap-3 sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
		</Dialog.Header>
		<label
			class="flex h-10 items-center gap-2 rounded-lg border border-input bg-background px-3 focus-within:border-ring"
		>
			<SearchIcon class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
			<input
				type="search"
				bind:value={query}
				aria-label={searchLabel}
				placeholder={searchLabel}
				class="h-full min-w-0 flex-1 bg-transparent text-base outline-none sm:text-sm"
			/>
		</label>
		<div class="-mx-2 min-h-0 flex-1 overflow-y-auto px-2">
			{#each sections as section (section.letter)}
				<div class="px-2 pt-2 pb-0.5 text-xs font-semibold text-muted-foreground">
					{section.letter}
				</div>
				<ul class="flex flex-col">
					{#each section.items as item (item.id)}
						<li>
							<label
								class="flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-2 text-sm hover:bg-secondary"
							>
								<input
									type="checkbox"
									checked={selected.includes(item.id)}
									onchange={(event) => toggle(item.id, event.currentTarget.checked)}
									class="size-4 shrink-0 accent-primary"
								/>
								<TypeIcon icon={item.icon} class="size-3.5 shrink-0 text-muted-foreground" />
								<span class="min-w-0 flex-1 truncate" title={item.title ?? item.label}>
									{item.label}
								</span>
								{#if item.hint}
									<span class="max-w-[40%] shrink-0 truncate text-xs text-muted-foreground">
										{item.hint}
									</span>
								{/if}
								{#if item.count !== null}
									<span class="w-8 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
										{formatNumber(item.count)}
									</span>
								{/if}
							</label>
						</li>
					{/each}
				</ul>
			{/each}
		</div>
		<Dialog.Footer>
			<Button onclick={() => (open = false)}>{m.facet_done()}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
