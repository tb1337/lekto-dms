<script lang="ts">
	import type { components } from '#lib/api/schema.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { signalSummary } from '#lib/signals.ts';

	// What a signal said in one run: the proposal, best classes, similar documents, names and
	// identifiers in the text, or why it abstained; for the OCR, how well it read each page.
	let { entry, lookup }: { entry: components['schemas']['LogEntry']; lookup: Lookup | null } =
		$props();

	const rows = $derived(signalSummary(entry, lookup));
</script>

{#each rows as row (row.label)}
	<dt class="text-muted-foreground">{row.label}</dt>
	<dd class="flex min-w-0 flex-wrap gap-x-3 gap-y-0.5 break-words">
		{#each row.items as item, index (index)}
			{#if item.href}
				<a href={item.href} class="text-brand hover:underline">{item.text}</a>
			{:else}
				<span>{item.text}</span>
			{/if}
		{/each}
	</dd>
{/each}
