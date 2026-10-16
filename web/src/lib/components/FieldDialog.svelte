<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import AssignmentList from '#lib/components/AssignmentList.svelte';
	import NativeSelect from '#lib/components/NativeSelect.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { FIELD_TYPES, fieldTypeLabel } from '#lib/fields.ts';
	import type { FieldDefinition, MasterData } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';

	type DataType = components['schemas']['FieldType'];

	// Add a field definition (`initial` null) or change one: name, description, choices, the
	// types it applies to and is required for. The data type is fixed once it exists.
	let {
		open = $bindable(false),
		initial = null,
		types,
		onsaved
	}: {
		open?: boolean;
		initial?: FieldDefinition | null;
		types: readonly MasterData[];
		onsaved: () => void;
	} = $props();

	let name = $state('');
	let dataType = $state<DataType>('text');
	let global = $state(true);
	let scope = $state<string[]>([]);
	// Required everywhere (global) or for these of its types.
	let required = $state(false);
	let requiredTypes = $state<string[]>([]);
	let choices = $state('');
	// What belongs in the field, for the language model (its name is often an internal one).
	let description = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);

	$effect(() => {
		if (!open) return;
		error = null;
		name = initial?.name ?? '';
		dataType = initial?.data_type ?? 'text';
		global = initial ? initial.document_type_ids === null : true;
		scope = initial?.document_type_ids ? [...initial.document_type_ids] : [];
		required = initial?.required ?? false;
		requiredTypes = initial ? [...initial.required_document_type_ids] : [];
		choices = initial ? initial.choices.join('\n') : '';
		description = initial?.description ?? '';
	});

	const isChoice = $derived((initial?.data_type ?? dataType) === 'choice');

	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		busy = true;
		error = null;
		const list = choices
			.split('\n')
			.map((line) => line.trim())
			.filter(Boolean);
		const document_type_ids = global ? null : scope;
		const requirement = {
			required: global && required,
			required_document_type_ids: global ? [] : requiredTypes.filter((id) => scope.includes(id))
		};
		try {
			if (initial === null) {
				await unwrap(
					api.POST('/api/v1/fields', {
						body: {
							name: name.trim(),
							data_type: dataType,
							description: description.trim() || null,
							document_type_ids,
							...requirement,
							...(dataType === 'choice' ? { choices: list } : {})
						}
					})
				);
			} else {
				await unwrap(
					api.PATCH('/api/v1/fields/{id}', {
						params: { path: { id: initial.id } },
						body: {
							name: name.trim(),
							description: description.trim() || null,
							document_type_ids,
							...requirement,
							...(initial.data_type === 'choice' ? { choices: list } : {})
						}
					})
				);
			}
			toast.success(m.master_saved());
			open = false;
			onsaved();
		} catch (failure) {
			error = describeError(failure);
		} finally {
			busy = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="max-w-lg">
		<form class="flex flex-col gap-4" onsubmit={save} novalidate>
			<Dialog.Header>
				<Dialog.Title>{initial === null ? m.master_add_field() : m.field_def_edit()}</Dialog.Title>
				<Dialog.Description>{m.field_def_hint()}</Dialog.Description>
			</Dialog.Header>
			<Field.Field>
				<Field.Label for="field-def-name">{m.field_name()}</Field.Label>
				<Input id="field-def-name" bind:value={name} maxlength={200} required />
			</Field.Field>
			<Field.Field>
				<Field.Label for="field-def-type">{m.field_def_type()}</Field.Label>
				<NativeSelect
					id="field-def-type"
					bind:value={dataType as string}
					disabled={initial !== null}
					options={FIELD_TYPES.map((type) => ({ value: type, label: fieldTypeLabel(type) }))}
				/>
			</Field.Field>
			<Field.Field>
				<Field.Label for="field-def-description">{m.field_def_description()}</Field.Label>
				<Textarea id="field-def-description" bind:value={description} rows={3} maxlength={300} />
				<Field.Description>{m.field_def_description_hint()}</Field.Description>
			</Field.Field>
			{#if isChoice}
				<Field.Field>
					<Field.Label for="field-def-choices">{m.field_def_choices()}</Field.Label>
					<Textarea id="field-def-choices" bind:value={choices} rows={4} />
					<Field.Description>{m.field_def_choices_hint()}</Field.Description>
				</Field.Field>
			{/if}
			<fieldset class="flex flex-col gap-2">
				<legend class="mb-1 text-sm font-medium">{m.field_def_scope()}</legend>
				<label class="flex items-center gap-2 text-sm">
					<input type="checkbox" bind:checked={global} class="size-4 accent-primary" />
					{m.field_def_scope_global()}
				</label>
				{#if global}
					<label class="flex items-center gap-2 pl-6 text-sm">
						<input type="checkbox" bind:checked={required} class="size-4 accent-primary" />
						{m.field_def_required_everywhere()}
					</label>
				{:else}
					<AssignmentList
						assigned={scope.map((id) => ({ id, required: requiredTypes.includes(id) }))}
						candidates={types}
						label={m.field_def_scope()}
						addLabel={m.field_def_add_type()}
						emptyLabel={m.field_def_no_type()}
						onchange={(items) => {
							scope = items.map((item) => item.id);
							requiredTypes = items.filter((item) => item.required).map((item) => item.id);
						}}
					/>
				{/if}
				<p class="text-sm text-muted-foreground">{m.field_def_required_hint()}</p>
			</fieldset>
			{#if error}<p class="text-sm text-destructive" role="alert">{error}</p>{/if}
			<Dialog.Footer>
				<Button type="button" variant="ghost" onclick={() => (open = false)}>{m.cancel()}</Button>
				<Button type="submit" disabled={busy || name.trim() === ''}>{m.save()}</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
