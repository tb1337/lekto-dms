<script lang="ts">
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { factsOf } from '#lib/step-details.ts';

	// What the text names (Tobi, 23.10.2026), as rows of its entry: the contacts as chips, the
	// identifiers with their contact, the identifiers no contact has, the persons with the
	// strength of the evidence in brackets.
	let { output, lookup }: { output: Record<string, unknown>; lookup: Lookup | null } = $props();

	const facts = $derived(factsOf(output, lookup));
</script>

<dt class="text-muted-foreground">{m.signal_named()}</dt>
<dd class="flex min-w-0 flex-wrap gap-1.5 py-0.5">
	{#each facts.named as name, index (index)}
		<span class="rounded-full border bg-card px-2.5 py-0.5 text-meta">{name}</span>
	{:else}
		<span class="text-muted-foreground">{m.signal_none()}</span>
	{/each}
</dd>
<dt class="text-muted-foreground">{m.signal_identifiers()}</dt>
<dd class="flex min-w-0 flex-col gap-0.5 break-words">
	{#each facts.identifiers as line, index (index)}
		<span>{line}</span>
	{:else}
		<span class="text-muted-foreground">{m.signal_none()}</span>
	{/each}
</dd>
{#if facts.unknown.length > 0}
	<dt class="text-muted-foreground">{m.signal_unknown_identifiers()}</dt>
	<dd class="flex min-w-0 flex-col gap-0.5 break-words">
		{#each facts.unknown as line, index (index)}<span>{line}</span>{/each}
	</dd>
{/if}
{#if 'persons' in output}
	<dt class="text-muted-foreground">{m.facts_persons()}</dt>
	<dd class="flex min-w-0 flex-col gap-0.5">
		{#each facts.persons as line, index (index)}
			<span>{line}</span>
		{:else}
			<span class="text-muted-foreground">{m.signal_none()}</span>
		{/each}
	</dd>
{/if}
