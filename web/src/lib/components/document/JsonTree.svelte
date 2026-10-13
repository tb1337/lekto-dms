<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { untrack } from 'svelte';
	import JsonTree from '#lib/components/document/JsonTree.svelte';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// JSON as a tree: objects and lists fold, with their size; what is folded is not built, so
	// a large file (Docling's structure of a long document) stays quick. Long lists come in
	// steps.
	let {
		value,
		name = null,
		depth = 0
	}: { value: unknown; name?: string | number | null; depth?: number } = $props();

	const STEP = 100;
	// Only the top opens by itself; then the reader decides.
	let open = $state(untrack(() => depth === 0));
	let limit = $state(STEP);

	const list = $derived(Array.isArray(value));
	const folds = $derived(value !== null && typeof value === 'object');
	const entries = $derived.by((): [string | number, unknown][] => {
		if (Array.isArray(value)) return value.map((child, index) => [index, child]);
		if (value !== null && typeof value === 'object') return Object.entries(value);
		return [];
	});
	const rest = $derived(entries.length - limit);
	const tone = $derived(
		typeof value === 'string'
			? 'text-brand'
			: typeof value === 'number'
				? 'text-foreground'
				: 'text-muted-foreground italic'
	);
</script>

{#snippet key()}
	{#if name !== null}
		<span class={typeof name === 'number' ? 'text-muted-foreground' : 'text-foreground'}>
			{typeof name === 'number' ? name : JSON.stringify(name)}</span
		><span class="text-muted-foreground">:&nbsp;</span>
	{/if}
{/snippet}

{#if folds}
	<details bind:open class="pl-5">
		<summary
			class="-ml-5 flex w-fit cursor-pointer list-none items-center gap-1 rounded hover:bg-muted [&::-webkit-details-marker]:hidden"
		>
			<ChevronRight
				class="size-3.5 shrink-0 text-muted-foreground transition-transform [details[open]>summary>&]:rotate-90"
				aria-hidden="true"
			/>
			<span>
				{@render key()}<span class="text-muted-foreground">{list ? '[' : '{'}</span>
				{#if !open}
					<span class="text-muted-foreground">…{list ? ']' : '}'}</span>
					<span class="ml-1 font-sans text-xs text-muted-foreground">
						{list
							? entries.length === 1
								? m.json_item()
								: m.json_items({ count: formatNumber(entries.length) })
							: entries.length === 1
								? m.json_key()
								: m.json_keys({ count: formatNumber(entries.length) })}
					</span>
				{/if}
			</span>
		</summary>
		{#if open}
			{#each entries.slice(0, limit) as [childName, child] (childName)}
				<JsonTree name={childName} value={child} depth={depth + 1} />
			{/each}
			{#if rest > 0}
				<button
					type="button"
					onclick={() => (limit += STEP)}
					class="my-0.5 font-sans text-xs text-brand hover:underline"
				>
					{m.json_more({ count: formatNumber(Math.min(STEP, rest)), total: formatNumber(rest) })}
				</button>
			{/if}
			<div class="-ml-5 pl-[1.125rem] text-muted-foreground">{list ? ']' : '}'}</div>
		{/if}
	</details>
{:else}
	<div class="pl-5 break-all">
		{@render key()}<span class={tone}>{JSON.stringify(value)}</span>
	</div>
{/if}
