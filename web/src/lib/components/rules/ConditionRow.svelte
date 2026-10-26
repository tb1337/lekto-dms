<script lang="ts">
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import X from '@lucide/svelte/icons/x';
	import MultiPicker from '#lib/components/MultiPicker.svelte';
	import Select from '#lib/components/Select.svelte';
	import { namedOptions, withChoice } from '#lib/components/rules/options.ts';
	import ValueInput from '#lib/components/rules/ValueInput.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { FACT_ROLES, roleLabel } from '#lib/facts.ts';
	import { session } from '#lib/session.svelte.ts';
	import { IDENTIFIER_KINDS, NUMBER_KINDS, PERSON_KINDS, labelOfKind } from '#lib/identifiers.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { CHANNEL_LABELS, fieldLabel, operatorLabel } from '#lib/rules/describe.ts';
	import { tagOptions } from '#lib/tags.ts';
	import { Choice } from '#lib/components/ui/choice/index.ts';
	import {
		CHANNELS,
		CONDITION_FIELDS,
		STEP_CONDITION_FIELDS,
		TAG_FIELDS,
		changeField,
		changeConditionField,
		changeOperator,
		operatorsFor,
		takesNoValue,
		type ConditionField,
		type ConditionNode,
		type Operator
	} from '#lib/rules/model.ts';

	// One condition: condition field (and the field), comparison and the value it needs.
	// `onunreadable` says while the value's text cannot be read (see `ValueInput`). In a
	// condition step (`steps`: the names of the steps before that ask) it may look at what a
	// step brought too.
	let {
		condition,
		lookup,
		error,
		steps = null,
		onremove,
		onup,
		ondown,
		onunreadable
	}: {
		condition: ConditionNode;
		lookup: Lookup;
		error?: string;
		steps?: readonly string[] | null;
		onunreadable?: (unreadable: boolean) => void;
		onremove: () => void;
		onup?: () => void;
		ondown?: () => void;
	} = $props();

	const field = $derived(lookup.fields.find((entry) => entry.id === condition.fieldId) ?? null);
	// A person's numbers (by kind or role) only for admins, as only they find documents by
	// them; a kind saved otherwise (over the API) is shown all the same.
	const factKindOptions = $derived(
		[
			...new Set<string>([
				...NUMBER_KINDS,
				...IDENTIFIER_KINDS,
				...(session.isAdmin ? PERSON_KINDS : []),
				...(condition.factKind ? [condition.factKind] : [])
			])
		].map((kind) => ({ value: kind, label: labelOfKind(kind) }))
	);
	const factRoleOptions = $derived([
		{ value: '', label: m.filter_fact_any_role() },
		...FACT_ROLES.filter(
			(role) => role !== 'person' || session.isAdmin || condition.factRole === 'person'
		).map((role) => ({ value: role, label: roleLabel(role) }))
	]);
	const operators = $derived(operatorsFor(condition, lookup.fields));
	const conditionFieldOptions = $derived(
		(steps === null ? CONDITION_FIELDS : STEP_CONDITION_FIELDS).map((field) => ({
			value: field,
			label: fieldLabel(field)
		}))
	);
	// What a step condition compares with: a text, a number or true/false; after or before a
	// number or a date.
	type Kind = 'text' | 'number' | 'date' | 'true' | 'false';
	const ordered = $derived(condition.op === 'gt' || condition.op === 'lt');
	const kinds = $derived(
		(ordered
			? (['number', 'date'] as const)
			: condition.op === 'contains'
				? (['text'] as const)
				: (['text', 'number', 'true', 'false'] as const)
		).map((kind) => ({ value: kind, label: KIND_LABELS[kind]() }))
	);
	const KIND_LABELS: Record<Kind, () => string> = {
		text: m.rule_value_text,
		number: m.rule_value_number,
		date: m.rule_value_date,
		true: m.rule_value_true,
		false: m.rule_value_false
	};
	const kind = $derived.by((): Kind => {
		const value = condition.value;
		if (typeof value === 'boolean') return value ? 'true' : 'false';
		if (typeof value === 'number') return 'number';
		return ordered ? 'date' : 'text';
	});
	function setKind(next: string) {
		if (next === 'true' || next === 'false') condition.value = next === 'true';
		else if (next === 'number') condition.value = 0;
		else condition.value = '';
	}
	function stepInput(text: string) {
		condition.value = kind === 'number' ? Number(text.replace(',', '.')) : text;
	}
	const operatorOptions = $derived(
		operators.map((op) => ({
			value: op,
			label: operatorLabel(condition.field, op, field?.data_type ?? null)
		}))
	);
	const fieldOptions = $derived(withChoice(namedOptions(lookup.fields), condition.fieldId ?? ''));
	/** The choices of an id field or the channel. */
	const choices = $derived.by(() => {
		switch (condition.field) {
			case 'contact':
				return lookup.contacts.map((entry) => ({ value: entry.id, label: entry.name }));
			case 'document_type':
			case 'relation':
				return lookup.documentTypes.map((entry) => ({ value: entry.id, label: entry.name }));
			case 'tags':
			case 'contact_group':
			case 'document_type_group':
				return tagOptions(lookup.tags, TAG_FIELDS[condition.field]);
			case 'topic':
				return tagOptions(lookup.tags, 'topic');
			case 'channel':
				return CHANNELS.map((channel) => ({ value: channel, label: CHANNEL_LABELS[channel]() }));
			case 'field':
				return field?.data_type === 'choice'
					? field.choices.map((choice) => ({ value: choice, label: choice }))
					: null;
			default:
				return null;
		}
	});
	const single = $derived(typeof condition.value === 'string' ? condition.value : '');
	const list = $derived(Array.isArray(condition.value) ? condition.value.map(String) : []);
	const textual = $derived(
		condition.field === 'text' || condition.op === 'contains' || condition.op === 'matches'
	);
	const valueLabel = m.rule_condition_value();
	const invalid = $derived(Boolean(error));
</script>

<div class="flex flex-col gap-2 rounded-xl border bg-background p-3" data-key={condition.key}>
	<div class="flex flex-wrap items-start gap-2">
		<Select
			aria-label={m.rule_condition_subject()}
			value={condition.field}
			options={conditionFieldOptions}
			onchange={(field) => changeConditionField(condition, field as ConditionField, lookup.fields)}
			class="h-10 w-full sm:w-44"
		/>
		{#if condition.field === 'step'}
			<Input
				aria-label={m.rule_step_path()}
				aria-invalid={invalid || undefined}
				placeholder={steps?.length ? `${steps[0]}.` : ''}
				title={m.rule_step_path_hint()}
				value={condition.path ?? ''}
				oninput={(event) => (condition.path = event.currentTarget.value.trim())}
				class="h-10 w-full font-mono sm:w-44"
			/>
		{/if}
		{#if condition.field === 'fact'}
			<!-- Its kind and its role, any role unless one is chosen; a person's for admins. -->
			<Select
				aria-label={m.facts_add_kind()}
				value={condition.factKind ?? ''}
				options={factKindOptions}
				onchange={(kind) => (condition.factKind = kind)}
				class="h-10 w-full sm:w-44"
			/>
			<Select
				aria-label={m.facts_decide_role()}
				value={condition.factRole ?? ''}
				options={factRoleOptions}
				onchange={(role) => (condition.factRole = role || null)}
				class="h-10 w-full sm:w-44"
			/>
		{/if}
		{#if condition.field === 'field'}
			<Select
				aria-label={m.rule_condition_field()}
				aria-invalid={invalid && !condition.fieldId}
				value={condition.fieldId ?? ''}
				options={fieldOptions}
				onchange={(id) => id && changeField(condition, id, lookup.fields)}
				class="h-10 w-full sm:w-44"
			/>
		{/if}
		<Select
			aria-label={m.rule_condition_operator()}
			value={condition.op}
			options={operatorOptions}
			onchange={(op) => changeOperator(condition, op as Operator, lookup.fields)}
			class="h-10 w-full sm:w-48"
		/>
		<div class="min-w-0 flex-1 basis-56">
			{#if takesNoValue(condition.op)}
				<span class="sr-only">{m.rule_no_value()}</span>
			{:else if condition.op === 'in' && choices}
				<MultiPicker
					label={valueLabel}
					{invalid}
					options={choices}
					selected={list}
					onchange={(next) => (condition.value = next)}
				/>
			{:else if condition.op === 'in'}
				<div class="flex flex-col gap-2">
					{#each list as entry, index (index)}
						<div class="flex gap-1">
							<Input
								aria-label={valueLabel}
								aria-invalid={invalid || undefined}
								value={entry}
								oninput={(event) =>
									(condition.value = list.map((item, at) =>
										at === index ? event.currentTarget.value : item
									))}
							/>
							<Button
								variant="ghost"
								size="icon"
								aria-label={m.rule_remove_value({ name: entry })}
								onclick={() => (condition.value = list.filter((_, at) => at !== index))}
							>
								<X aria-hidden="true" />
							</Button>
						</div>
					{/each}
					<Button
						variant="outline"
						size="sm"
						class="w-fit"
						onclick={() => (condition.value = [...list, ''])}
					>
						{m.rule_add_value()}
					</Button>
				</div>
			{:else if choices && condition.field !== 'field'}
				<Select
					aria-label={valueLabel}
					aria-invalid={invalid || undefined}
					value={single}
					options={withChoice(choices, single)}
					onchange={(next) => (condition.value = next)}
					class="h-10"
				/>
			{:else if condition.field === 'step'}
				<div class="flex gap-1">
					{#if kinds.length > 1}
						<Select
							aria-label={m.rule_value_kind()}
							value={kind}
							options={kinds}
							onchange={setKind}
							class="h-10 w-28 shrink-0"
						/>
					{/if}
					{#if kind === 'number' || kind === 'text' || kind === 'date'}
						<Input
							type={kind === 'number' ? 'number' : kind === 'date' ? 'date' : 'text'}
							aria-label={valueLabel}
							aria-invalid={invalid || undefined}
							value={typeof condition.value === 'number' ? String(condition.value) : single}
							oninput={(event) => stepInput(event.currentTarget.value)}
						/>
					{/if}
				</div>
			{:else if condition.field === 'document_date'}
				<Input
					type={single === '' || /^\d{4}-\d{2}-\d{2}$/.test(single) ? 'date' : 'text'}
					aria-label={valueLabel}
					aria-invalid={invalid || undefined}
					value={single}
					oninput={(event) => (condition.value = event.currentTarget.value)}
				/>
			{:else if condition.field === 'field'}
				<ValueInput
					{field}
					{textual}
					{invalid}
					label={valueLabel}
					value={condition.value}
					onchange={(next) => (condition.value = next)}
					{onunreadable}
				/>
			{:else}
				<Input
					aria-label={valueLabel}
					aria-invalid={invalid || undefined}
					value={single}
					oninput={(event) => (condition.value = event.currentTarget.value)}
				/>
			{/if}
			{#if condition.op === 'matches'}
				<Choice bind:checked={condition.caseSensitive} class="mt-2">
					{m.rule_case_sensitive()}
				</Choice>
			{/if}
		</div>
		<div class="flex gap-0.5">
			<Button
				variant="ghost"
				size="icon"
				aria-label={m.rule_move_up()}
				disabled={!onup}
				onclick={() => onup?.()}
			>
				<ArrowUp aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon"
				aria-label={m.rule_move_down()}
				disabled={!ondown}
				onclick={() => ondown?.()}
			>
				<ArrowDown aria-hidden="true" />
			</Button>
			<Button variant="ghost" size="icon" aria-label={m.rule_remove()} onclick={onremove}>
				<Trash2 aria-hidden="true" />
			</Button>
		</div>
	</div>
	{#if error}<Field.Error>{error}</Field.Error>{/if}
</div>
