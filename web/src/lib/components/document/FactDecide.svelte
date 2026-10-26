<script lang="ts">
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import {
		FACT_ROLES,
		onlyByPerson,
		roleLabel,
		type FactDecision,
		type FactRole,
		type KeptFact
	} from '#lib/facts.ts';
	import { kindLabel } from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A person's decision about one fact of the document: its value and role corrected (for
	// admins at the document's contact too), rejected, or a decision withdrawn. A rejected fact
	// is only restored.
	let {
		fact,
		contact = null,
		busy = false,
		ondecide,
		oncancel
	}: {
		fact: KeptFact;
		/** The document's contact an admin may correct the value at too; null: not offered. */
		contact?: string | null;
		busy?: boolean;
		ondecide: (decision: FactDecision) => void;
		oncancel: () => void;
	} = $props();

	// What the form starts from: the fact as it was opened.
	const shownValue = (of: KeptFact) => of.written ?? of.value;
	let value = $state('');
	let role = $state<FactRole>('contact');
	let atContact = $state(false);
	$effect.pre(() => {
		value = shownValue(fact);
		role = fact.role;
		atContact = false;
	});

	const rejected = $derived(fact.state === 'rejected');
	const decided = $derived(fact.state !== undefined && fact.state !== 'found');
	const changedValue = $derived(value.trim() !== '' && value.trim() !== shownValue(fact));
	const changed = $derived(changedValue || role !== fact.role);
	const base = $derived({ kind: fact.kind, value: fact.value });

	function correct() {
		if (!changed) return;
		ondecide({
			...base,
			action: 'correct',
			...(role !== fact.role ? { role } : {}),
			...(changedValue ? { new_value: value.trim() } : {}),
			...(changedValue && atContact ? { at_contact: true } : {})
		});
	}
</script>

<form
	class="mx-2.5 mb-2.5 flex flex-col gap-2.5 rounded-xl border bg-card p-3"
	onsubmit={(event) => {
		event.preventDefault();
		correct();
	}}
>
	<span class="text-sm font-medium">{m.facts_decide_title({ kind: kindLabel(fact.kind) })}</span>
	{#if rejected}
		<span class="text-xs text-muted-foreground">{m.facts_decide_rejected_hint()}</span>
	{:else}
		<label class="flex flex-col gap-1 text-sm">
			<span class="text-xs text-muted-foreground">{m.facts_decide_value()}</span>
			<Input class="font-mono" bind:value autocomplete="off" spellcheck="false" />
		</label>
		<label class="flex flex-col gap-1 text-sm">
			<span class="text-xs text-muted-foreground">{m.facts_decide_role()}</span>
			<Select
				bind:value={role}
				aria-label={m.facts_decide_role()}
				options={FACT_ROLES.map((item) => ({ value: item, label: roleLabel(item) }))}
			/>
		</label>
		{#if contact && changedValue}
			<label class="flex items-start gap-2.5 text-sm">
				<input type="checkbox" bind:checked={atContact} class="mt-1 accent-primary" />
				<span>{m.facts_decide_at_contact({ contact })}</span>
			</label>
		{/if}
	{/if}
	<div class="flex flex-wrap justify-end gap-2">
		<Button type="button" variant="ghost" size="sm" onclick={oncancel}>{m.cancel()}</Button>
		{#if rejected}
			<Button
				type="button"
				size="sm"
				disabled={busy}
				onclick={() => ondecide({ ...base, action: 'withdraw' })}
			>
				{m.facts_decide_restore()}
			</Button>
		{:else}
			{#if decided}
				<Button
					type="button"
					variant="outline"
					size="sm"
					disabled={busy}
					onclick={() => ondecide({ ...base, action: 'withdraw' })}
				>
					{onlyByPerson(fact) ? m.facts_decide_remove() : m.facts_decide_undo()}
				</Button>
			{/if}
			{#if !onlyByPerson(fact)}
				<Button
					type="button"
					variant="outline"
					size="sm"
					disabled={busy}
					onclick={() => ondecide({ ...base, action: 'reject' })}
				>
					{m.facts_decide_reject()}
				</Button>
			{/if}
			<Button type="submit" size="sm" disabled={busy || !changed}>
				{m.facts_decide_save()}
			</Button>
		{/if}
	</div>
</form>
