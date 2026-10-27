<script lang="ts">
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import {
		FACT_ROLES,
		KIND_ROLES,
		roleLabel,
		type FactDecision,
		type FactRole
	} from '#lib/facts.ts';
	import {
		IDENTIFIER_KINDS,
		NUMBER_KINDS,
		PERSON_KINDS,
		kindLabel,
		type IdentifierKind
	} from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A fact the sources did not find, added by a person: its kind (a person's kinds only for
	// admins), the value as the document writes it, and its role (the kind's unless chosen).
	let {
		admin,
		busy = false,
		ondecide,
		oncancel
	}: {
		admin: boolean;
		busy?: boolean;
		ondecide: (decision: FactDecision) => void;
		oncancel: () => void;
	} = $props();

	const kinds = $derived([
		...new Set<IdentifierKind>([
			...NUMBER_KINDS,
			...IDENTIFIER_KINDS,
			...(admin ? PERSON_KINDS : [])
		])
	]);
	let kind = $state<IdentifierKind>('invoice_number');
	let value = $state('');
	let role = $state<FactRole>(KIND_ROLES.invoice_number);

	function choose(next: string) {
		kind = next as IdentifierKind;
		role = KIND_ROLES[kind];
	}
</script>

<form
	class="flex flex-col gap-2.5 rounded-xl border bg-card p-3"
	onsubmit={(event) => {
		event.preventDefault();
		if (value.trim()) ondecide({ action: 'add', kind, value: value.trim(), role });
	}}
>
	<span class="text-sm font-medium">{m.facts_add()}</span>
	<label class="flex flex-col gap-1 text-sm">
		<span class="text-xs text-muted-foreground">{m.facts_add_kind()}</span>
		<Select
			value={kind}
			onchange={choose}
			aria-label={m.facts_add_kind()}
			options={kinds.map((item) => ({ value: item, label: kindLabel(item) }))}
		/>
	</label>
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
	<div class="flex justify-end gap-2">
		<Button type="button" variant="ghost" size="sm" onclick={oncancel}>{m.cancel()}</Button>
		<Button type="submit" size="sm" disabled={busy || !value.trim()}>{m.facts_add_save()}</Button>
	</div>
</form>
