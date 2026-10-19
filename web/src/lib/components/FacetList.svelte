<script lang="ts" module>
	export interface FacetItem {
		id: string;
		label: string;
		/** The tooltip, e.g. the path of a tag. */
		title?: string;
		/** How many documents it would add or keep; null where the list shows none. */
		count: number | null;
		/** A colour dot (CSS colour) before the name, e.g. a tag's colour. */
		dot?: string | null;
	}
</script>

<script lang="ts">
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A group of the filters: its values with a box each and, where known, how many documents
	// they hold, most first. The first `limit` show, and the chosen ones always; the rest
	// behind "N more", with a field to search them where there are many.
	let {
		title,
		items,
		selected,
		onchange,
		limit = 6
	}: {
		title: string;
		items: readonly FacetItem[];
		selected: readonly string[];
		onchange: (next: string[]) => void;
		limit?: number;
	} = $props();

	const id = $props.id();
	let open = $state(false);
	let query = $state('');

	const hidden = $derived(Math.max(0, items.length - limit));
	const shown = $derived.by(() => {
		if (open) {
			const words = query.trim().toLocaleLowerCase();
			return words ? items.filter((item) => item.label.toLocaleLowerCase().includes(words)) : items;
		}
		return items.filter((item, index) => index < limit || selected.includes(item.id));
	});

	function toggle(item: FacetItem, checked: boolean) {
		onchange(checked ? [...selected, item.id] : selected.filter((entry) => entry !== item.id));
	}
</script>

{#if items.length > 0}
	<section class="flex flex-col gap-0.5" aria-labelledby="{id}-title">
		<h3
			id="{id}-title"
			class="mb-1 px-2 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
		>
			{title}
		</h3>
		{#if open && items.length > 12}
			<input
				type="search"
				bind:value={query}
				aria-label={m.facet_search({ title })}
				placeholder={m.facet_search({ title })}
				class="mx-1 mb-1 h-8 rounded-md border border-input bg-background px-2 text-sm outline-none focus:border-ring"
			/>
		{/if}
		<ul class="flex flex-col">
			{#each shown as item (item.id)}
				{@const checked = selected.includes(item.id)}
				<li>
					<label
						class={[
							'flex min-h-8 cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1 text-sm transition-colors hover:bg-secondary',
							checked && 'bg-panel'
						]}
						title={item.title ?? item.label}
					>
						<input
							type="checkbox"
							{checked}
							onchange={(event) => toggle(item, event.currentTarget.checked)}
							class="size-4 shrink-0 accent-primary"
						/>
						{#if item.dot}
							<span
								aria-hidden="true"
								class="size-2 shrink-0 rounded-full"
								style:background-color={item.dot}
							></span>
						{/if}
						<span class="min-w-0 flex-1 truncate">{item.label}</span>
						{#if item.count !== null}
							<span class="shrink-0 text-xs text-muted-foreground tabular-nums">
								{formatNumber(item.count)}
							</span>
						{/if}
					</label>
				</li>
			{/each}
		</ul>
		{#if hidden > 0}
			<button
				type="button"
				class="w-fit rounded-md px-2 py-1 text-left text-sm text-brand hover:underline"
				aria-expanded={open}
				onclick={() => {
					open = !open;
					query = '';
				}}
			>
				{open ? m.facet_fewer() : m.facet_more({ count: formatNumber(hidden) })}
			</button>
		{/if}
	</section>
{/if}
