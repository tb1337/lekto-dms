<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
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
	import Chip from '#lib/components/Chip.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { refOf } from '#lib/fact-refs.svelte.ts';

	// The facts the documents have (#145): those chosen, each to let go, and one more by its
	// kind, value and role, any of them open (a value needs its kind). A person's kinds only
	// for admins: the API refuses them to anyone else. A typed value enters the filter as its
	// reference, never as written (web/DESIGN.md, "No plain data in addresses"); one that is
	// none of its kind says why below the field.
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
	let busy = $state(false);
	let problem = $state<string | null>(null);
	const ready = $derived(Boolean(kind || role) && !(value.trim() && !kind) && !busy);

	async function add() {
		if (!ready) return;
		const written = value.trim();
		let ref: string | null = null;
		if (written) {
			busy = true;
			try {
				ref = await refOf(kind as IdentifierKind, written);
			} catch (error) {
				problem = describeError(error);
				return;
			} finally {
				busy = false;
			}
		}
		const fact = factFilter(
			(kind || null) as IdentifierKind | null,
			ref,
			(role || null) as FactRole | null
		);
		if (!facts.includes(fact)) onchange([...facts, fact]);
		value = '';
	}
</script>

<div class="flex flex-col gap-2">
	{#each facts as fact (fact)}
		<Chip
			variant="selected"
			class="self-start"
			removeLabel={m.filter_remove({ name: factFilterLabel(fact) })}
			onremove={() => onchange(facts.filter((entry) => entry !== fact))}
			>{factFilterLabel(fact)}</Chip
		>
	{/each}
	<form
		class="flex flex-col gap-2"
		onsubmit={(event) => {
			event.preventDefault();
			void add();
		}}
	>
		<Select
			aria-label={m.facts_add_kind()}
			value={kind}
			onchange={(next) => {
				kind = next;
				problem = null;
				if (!next) value = ''; // a value needs its kind
			}}
			options={[
				{ value: '', label: m.filter_fact_any_kind() },
				...kinds.map((item) => ({ value: item, label: kindLabel(item) }))
			]}
			class="h-9 w-full"
		/>
		<Input
			class="h-9 font-mono"
			bind:value
			oninput={() => (problem = null)}
			aria-label={m.facts_decide_value()}
			aria-invalid={problem ? true : undefined}
			placeholder={m.filter_fact_value()}
			disabled={!kind}
			autocomplete="off"
			spellcheck="false"
		/>
		{#if problem}<Field.Error>{problem}</Field.Error>{/if}
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
