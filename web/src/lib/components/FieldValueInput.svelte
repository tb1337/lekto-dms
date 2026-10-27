<script lang="ts">
	import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
	import { type InputValue, isMoney, isPeriod } from '#lib/fields.ts';
	import Select from '#lib/components/Select.svelte';
	import PeriodInput from '#lib/components/PeriodInput.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import DateInput from '#lib/components/DateInput.svelte';

	// The input for one field, by its data type; the caller labels it (`id`). An empty field
	// removes the value. `onunreadable` says while a period's text cannot be read (the value
	// then is not what the field shows; see `PeriodInput`).
	let {
		field,
		value = $bindable(),
		error,
		id,
		disabled = false,
		onunreadable
	}: {
		field: FieldDefinition;
		value: InputValue;
		error?: string;
		id: string;
		disabled?: boolean;
		onunreadable?: (unreadable: boolean) => void;
	} = $props();

	const yesNo = $derived([
		{ value: '', label: m.value_unset() },
		{ value: 'true', label: m.value_yes() },
		{ value: 'false', label: m.value_no() }
	]);
	const choices = $derived([
		{ value: '', label: m.value_unset() },
		...field.choices.map((choice) => ({ value: choice, label: choice }))
	]);
</script>

{#if field.data_type === 'amount' && isMoney(value)}
	<div class="flex gap-2">
		<Input
			{id}
			inputmode="decimal"
			bind:value={value.amount}
			{disabled}
			aria-invalid={error ? true : undefined}
			class="flex-1"
		/>
		<Input
			bind:value={value.currency}
			maxlength={3}
			{disabled}
			aria-label={m.field_currency()}
			class="w-24 uppercase"
		/>
	</div>
{:else if field.data_type === 'period' && isPeriod(value)}
	<PeriodInput bind:value {id} {disabled} invalid={Boolean(error)} {onunreadable} />
{:else if field.data_type === 'boolean' && typeof value === 'string'}
	<Select {id} bind:value {disabled} options={yesNo} aria-invalid={error ? true : undefined} />
{:else if field.data_type === 'choice' && typeof value === 'string'}
	<Select {id} bind:value {disabled} options={choices} aria-invalid={error ? true : undefined} />
{:else if field.data_type === 'date' && typeof value === 'string'}
	<DateInput {id} label={field.name} bind:value {disabled} invalid={!!error} />
{:else if typeof value === 'string'}
	<Input
		{id}
		bind:value
		{disabled}
		type={field.data_type === 'link' ? 'url' : 'text'}
		inputmode={field.data_type === 'number' ? 'decimal' : undefined}
		aria-invalid={error ? true : undefined}
	/>
{/if}
{#if error}<Field.Error>{error}</Field.Error>{/if}
