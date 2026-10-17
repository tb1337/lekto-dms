<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import LucideIcon from '#lib/components/LucideIcon.svelte';
	import { CURATED } from '#lib/icons/curated.ts';
	import { AREA_LABELS, iconLabel } from '#lib/icons/labels.ts';
	import { searchIcons } from '#lib/icons/search.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// An icon, or none: the chosen one and, opened in place, the icons offered first by areas of
	// life, and a search over every Lucide icon (their names, and the words of the ones offered
	// first in either language). Icons load as they come into view.
	let {
		value = $bindable(null),
		id
	}: {
		value?: string | null;
		id: string;
	} = $props();

	let open = $state(false);
	let query = $state('');
	const found = $derived(query.trim() ? searchIcons(query) : null);

	function choose(name: string | null) {
		value = name;
		open = false;
		query = '';
	}
</script>

{#snippet tile(name: string)}
	<button
		type="button"
		class="grid aspect-square place-items-center rounded-lg border border-transparent text-foreground transition-colors hover:border-border hover:bg-secondary aria-pressed:border-primary aria-pressed:bg-primary/10"
		aria-label={iconLabel(name)}
		title={name}
		aria-pressed={value === name}
		onclick={() => choose(name)}
	>
		<LucideIcon {name} lazy class="size-5" />
	</button>
{/snippet}

<div class="flex flex-col gap-2" role="group" aria-labelledby="{id}-label">
	<div class="flex flex-wrap items-center gap-2">
		<span
			class="grid size-10 shrink-0 place-items-center rounded-xl border bg-card"
			aria-hidden="true"
		>
			{#if value}<LucideIcon name={value} class="size-5" />{/if}
		</span>
		<span
			id="{id}-value"
			class={cn('min-w-0 flex-1 truncate text-sm', value ? 'font-mono' : 'text-muted-foreground')}
		>
			{value ?? m.icon_none()}
		</span>
		<Button
			variant="outline"
			size="sm"
			aria-expanded={open}
			aria-controls="{id}-panel"
			aria-describedby="{id}-value"
			onclick={() => (open = !open)}
		>
			{open ? m.icon_done() : m.icon_choose()}
		</Button>
		{#if value}
			<Button variant="ghost" size="sm" onclick={() => choose(null)}>{m.icon_remove()}</Button>
		{/if}
	</div>
	{#if open}
		<div id="{id}-panel" class="flex flex-col gap-3 rounded-xl border bg-card p-3">
			<Input
				type="search"
				bind:value={query}
				placeholder={m.icon_search()}
				aria-label={m.icon_search()}
			/>
			<div class="flex max-h-72 flex-col gap-4 overflow-y-auto pr-1">
				{#if found}
					{#if found.names.length === 0}
						<p class="text-sm text-muted-foreground">{m.icon_search_none()}</p>
					{:else}
						<div class="grid grid-cols-[repeat(auto-fill,minmax(2.75rem,1fr))] gap-1">
							{#each found.names as name (name)}{@render tile(name)}{/each}
						</div>
						{#if found.total > found.names.length}
							<p class="text-sm text-muted-foreground">
								{m.icon_search_more({ count: found.total - found.names.length })}
							</p>
						{/if}
					{/if}
				{:else}
					{#each CURATED as group (group.area)}
						<section class="flex flex-col gap-1.5" aria-label={AREA_LABELS[group.area]()}>
							<h4 class="text-xs font-medium text-muted-foreground">
								{AREA_LABELS[group.area]()}
							</h4>
							<div class="grid grid-cols-[repeat(auto-fill,minmax(2.75rem,1fr))] gap-1">
								{#each group.icons as name (name)}{@render tile(name)}{/each}
							</div>
						</section>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>
