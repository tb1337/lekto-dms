<script lang="ts">
	import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
	import { type InputValue, isMoney } from '#lib/fields.ts';
	import NativeSelect from '#lib/components/NativeSelect.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The input for one field, by its data type; the caller labels it (`id`). An empty field
	// removes the value.
	let {
		field,
		value = $bindable(),
		error,
		id,
		disabled = false
	}: {
		field: FieldDefinition;
		value: InputValue;
		error?: string;
		id: string;
		disabled?: boolean;
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
{:else if field.data_type === 'boolean' && typeof value === 'string'}
	<NativeSelect
		{id}
		bind:value
		{disabled}
		options={yesNo}
		aria-invalid={error ? true : undefined}
	/>
{:else if field.data_type === 'choice' && typeof value === 'string'}
	<NativeSelect
		{id}
		bind:value
		{disabled}
		options={choices}
		aria-invalid={error ? true : undefined}
	/>
{:else if typeof value === 'string'}
	<Input
		{id}
		bind:value
		{disabled}
		type={field.data_type === 'date' ? 'date' : field.data_type === 'link' ? 'url' : 'text'}
		inputmode={field.data_type === 'number' ? 'decimal' : undefined}
		aria-invalid={error ? true : undefined}
	/>
{/if}
{#if error}<Field.Error>{error}</Field.Error>{/if}
