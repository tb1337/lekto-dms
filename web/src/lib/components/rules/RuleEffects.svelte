<script lang="ts">
	import type { components } from '#lib/api/schema.ts';
	import { describeValue, fieldLabel } from '#lib/describe.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { reasonText, reasonsText } from '#lib/reasons.ts';

	// What a rule does to a document: field old → new, the webhooks it sends to, then its
	// notes (skipped, conflicts, …) and the requests that would not go.
	let {
		effects,
		notes = [],
		sends = [],
		refused = [],
		lookup
	}: {
		effects: readonly components['schemas']['RuleEffectOut'][];
		notes?: readonly components['schemas']['RuleNoteOut'][];
		/** Ids of the webhooks it sends through. */
		sends?: readonly string[];
		refused?: readonly components['schemas']['ReasonOut'][];
		lookup: Lookup | null;
	} = $props();

	const webhookName = (id: string) =>
		lookup?.webhooks?.find((webhook) => webhook.id === id)?.name ?? m.thing_webhook();
</script>

<ul class="flex flex-col gap-0.5">
	{#each effects as effect (effect.field)}
		<li>
			{fieldLabel(effect.field, lookup)}:
			{describeValue(effect.old, lookup)} → {describeValue(effect.new, lookup)}
		</li>
	{/each}
	{#each sends as id (id)}
		<li>{m.rule_sends_to({ webhook: webhookName(id) })}</li>
	{/each}
	{#each notes as note (note.field + note.kind)}
		<li class="text-muted-foreground">
			{fieldLabel(note.field, lookup)}:
			{reasonsText(note.reasons, note.reason, { field: (name) => fieldLabel(name, lookup) })}
		</li>
	{/each}
	{#each refused as reason, index (index)}
		<li class="text-muted-foreground">{reasonText(reason)}</li>
	{/each}
</ul>
