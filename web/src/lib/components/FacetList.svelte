<script lang="ts" module>
	export interface FacetItem {
		id: string;
		label: string;
		/** The tooltip, e.g. the path of a tag. */
		title?: string;
		/** How many documents it would add or keep; null where none is known or shown. */
		count: number | null;
		/** A type's icon. */
		icon?: string | null;
		/** What it belongs to, e.g. a contact's groups (in the list of all). */
		hint?: string;
	}
</script>

<script lang="ts">
	import SearchIcon from '@lucide/svelte/icons/search';
	import FacetPicker from '#lib/components/FacetPicker.svelte';
	import TypeIcon from '#lib/components/TypeIcon.svelte';
	import { formatNumber } from '#lib/i18n.ts';

	// A long list of a group of the filters, kept short: the most frequent values (`top`, most
	// first) and the chosen ones with a box each, a field that searches all of them, and every
	// one of them (`items`) to search and choose from in a picker.
	let {
		heading,
		top,
		items,
		selected,
		onchange,
		searchLabel,
		allLabel,
		pickerTitle,
		limit = 5
	}: {
		heading: string;
		top: readonly FacetItem[];
		items: readonly FacetItem[];
		selected: readonly string[];
		onchange: (next: string[]) => void;
		searchLabel: string;
		allLabel: string;
		/** The title of the picker of all values. */
		pickerTitle: string;
		limit?: number;
	} = $props();

	const id = $props.id();
	let query = $state('');
	let picking = $state(false);
	const shown = $derived.by(() => {
		const words = query.trim().toLocaleLowerCase();
		if (words) {
			return items.filter((item) => item.label.toLocaleLowerCase().includes(words)).slice(0, 8);
		}
		const first = top.slice(0, limit);
		const chosen = items.filter(
			(item) => selected.includes(item.id) && !first.some((entry) => entry.id === item.id)
		);
		return [...first, ...chosen];
	});

	function toggle(itemId: string, checked: boolean) {
		onchange(checked ? [...selected, itemId] : selected.filter((entry) => entry !== itemId));
	}
</script>

{#if items.length > 0}
	<div class="flex flex-col gap-1" role="group" aria-labelledby="{id}-heading">
		<span id="{id}-heading" class="text-xs text-muted-foreground">{heading}</span>
		{#if items.length > limit}
			<label
				class="flex h-8 items-center gap-2 rounded-lg border border-input bg-background px-2.5 focus-within:border-ring"
			>
				<SearchIcon class="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
				<input
					type="search"
					bind:value={query}
					aria-label={searchLabel}
					placeholder={searchLabel}
					class="h-full min-w-0 flex-1 bg-transparent text-base outline-none sm:text-sm"
				/>
			</label>
		{/if}
		<ul class="flex flex-col">
			{#each shown as item (item.id)}
				<li>
					<label
						class="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-lg px-1.5 text-sm hover:bg-secondary"
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
						{#if item.count !== null}
							<span class="shrink-0 text-xs text-muted-foreground tabular-nums">
								{formatNumber(item.count)}
							</span>
						{/if}
					</label>
				</li>
			{/each}
		</ul>
		{#if items.length > limit}
			<button
				type="button"
				class="w-fit px-1.5 text-sm text-brand hover:underline"
				onclick={() => (picking = true)}
			>
				{allLabel}
			</button>
			<FacetPicker
				bind:open={picking}
				title={pickerTitle}
				{searchLabel}
				{items}
				{selected}
				{onchange}
			/>
		{/if}
	</div>
{/if}
