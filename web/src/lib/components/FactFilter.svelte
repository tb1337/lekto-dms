<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { FACT_ROLES, factFilter, factFilterLabel, roleLabel, type FactRole } from '#lib/facts.ts';
	import {
		IDENTIFIER_KINDS,
		NUMBER_KINDS,
		PERSON_KINDS,
		kindLabel,
		type IdentifierKind
	} from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The facts the documents have (#145): those chosen, each to let go, and one more by its
	// kind, value and role, any of them open (a value needs its kind). A person's kinds only
	// for admins: the API refuses them to anyone else.
	let {
		facts,
		admin,
		onchange
	}: {
		facts: readonly string[];
		admin: boolean;
		onchange: (facts: string[]) => void;
	} = $props();

	const kinds = $derived([
		...new Set<IdentifierKind>([
			...NUMBER_KINDS,
			...IDENTIFIER_KINDS,
			...(admin ? PERSON_KINDS : [])
		])
	]);
	let kind = $state('');
	let value = $state('');
	let role = $state('');
	const ready = $derived(Boolean(kind || role) && !(value.trim() && !kind));

	function add() {
		if (!ready) return;
		const fact = factFilter(
			(kind || null) as IdentifierKind | null,
			value.trim() || null,
			(role || null) as FactRole | null
		);
		if (!facts.includes(fact)) onchange([...facts, fact]);
		value = '';
	}
</script>

<div class="flex flex-col gap-2">
	{#each facts as fact (fact)}
		<span
			class="inline-flex max-w-full items-center gap-1.5 self-start rounded-full border bg-card pr-1 pl-3 text-sm"
		>
			<span class="truncate">{factFilterLabel(fact)}</span>
			<button
				type="button"
				class="grid size-6 shrink-0 place-items-center rounded-full hover:bg-secondary"
				aria-label={m.filter_remove({ name: factFilterLabel(fact) })}
				onclick={() => onchange(facts.filter((entry) => entry !== fact))}
			>
				<X class="size-3.5" aria-hidden="true" />
			</button>
		</span>
	{/each}
	<form
		class="flex flex-col gap-2"
		onsubmit={(event) => {
			event.preventDefault();
			add();
		}}
	>
		<Select
			aria-label={m.facts_add_kind()}
			bind:value={kind}
			options={[
				{ value: '', label: m.filter_fact_any_kind() },
				...kinds.map((item) => ({ value: item, label: kindLabel(item) }))
			]}
			class="h-9 w-full"
		/>
		<Input
			class="h-9 font-mono"
			bind:value
			aria-label={m.facts_decide_value()}
			placeholder={m.filter_fact_value()}
			disabled={!kind}
			autocomplete="off"
			spellcheck="false"
		/>
		<Select
			aria-label={m.facts_decide_role()}
			bind:value={role}
			options={[
				{ value: '', label: m.filter_fact_any_role() },
				...FACT_ROLES.map((item) => ({ value: item, label: roleLabel(item) }))
			]}
			class="h-9 w-full"
		/>
		<Button type="submit" variant="outline" size="sm" class="self-start" disabled={!ready}>
			<Plus aria-hidden="true" />
			{m.filter_fact_add()}
		</Button>
	</form>
</div>
