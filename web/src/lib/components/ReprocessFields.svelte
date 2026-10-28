<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.ts';
	import Select from '#lib/components/Select.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { m } from '#lib/paraglide/messages.js';

	type ReprocessNode = components['schemas']['ReprocessNode'];

	// The fields of "Neu verarbeiten", for one document and for many: the step to start from
	// (`nodes`, as the pipeline offers them), then what the caller adds (`children`: a question
	// about the vision model, the model's cost) and a `note` on what the step means for the text.
	let {
		id,
		nodes,
		fromNode = $bindable('ocr'),
		note = null,
		children
	}: {
		id: string;
		nodes: readonly { value: ReprocessNode; label: string }[];
		fromNode?: ReprocessNode;
		note?: string | null;
		children?: Snippet;
	} = $props();
</script>

<Field.Field>
	<Field.Label for={id}>{m.reprocess_from()}</Field.Label>
	<Select {id} bind:value={fromNode} options={nodes} />
</Field.Field>
{@render children?.()}
{#if note}
	<p class="text-sm text-muted-foreground">{note}</p>
{/if}
