<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import AssignmentList from '#lib/components/AssignmentList.svelte';
	import EditorShell from '#lib/components/EditorShell.svelte';
	import HintLabel from '#lib/components/HintLabel.svelte';
	import InfoHint from '#lib/components/InfoHint.svelte';
	import Select from '#lib/components/Select.svelte';
	import { Switch } from '#lib/components/ui/switch/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { FIELD_TYPES, fieldTypeLabel } from '#lib/fields.ts';
	import type { FieldDefinition, MasterData } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	type DataType = components['schemas']['FieldType'];

	// Add a field definition (`initial` null) or change one: name, description, choices, the
	// types it applies to and is required for; delete one. The data type is fixed once it
	// exists; the key templates use is shown.
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
	// Set by hand only: the language model is never asked for it (issue #52).
	let manual = $state(false);
	let error = $state<string | null>(null);
	let busy = $state(false);
	// The types it applies to stand in a tab of their own (Tobi, 20.10.2026).
	let tab = $state('general');
	const tabs = $derived([
		{ value: 'general', label: m.master_tab_general() },
		{
			value: 'types',
			label: m.master_types(),
			count: global ? m.field_def_scope_all_short() : scope.length
		}
	]);

	$effect(() => {
		if (!open) return;
		tab = 'general';
		error = null;
		name = initial?.name ?? '';
		dataType = initial?.data_type ?? 'text';
		global = initial ? initial.document_type_ids === null : true;
		scope = initial?.document_type_ids ? [...initial.document_type_ids] : [];
		required = initial?.required ?? false;
		requiredTypes = initial ? [...initial.required_document_type_ids] : [];
		choices = initial ? initial.choices.join('\n') : '';
		description = initial?.description ?? '';
		manual = initial?.assignment === 'manual';
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
		const assignment = manual ? ('manual' as const) : ('auto' as const);
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
							assignment,
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
							assignment,
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

	async function remove() {
		if (!initial) return;
		await unwrap(api.DELETE('/api/v1/fields/{id}', { params: { path: { id: initial.id } } }));
		toast.success(m.master_deleted());
		open = false;
		onsaved();
	}
</script>

<EditorShell
	bind:open
	title={initial === null ? m.master_add_field() : m.field_def_edit()}
	shortTitle={initial === null ? m.master_add_field() : m.master_field()}
	submitLabel={m.save()}
	{busy}
	disabled={name.trim() === ''}
	{error}
	onsubmit={save}
	ondelete={initial ? remove : undefined}
	deleteTitle={m.master_delete({ name: initial?.name ?? '' })}
	deleteDescription={m.master_delete_confirm()}
	{tabs}
	bind:tab
	class="h-[min(46.25rem,calc(100dvh-2rem))] sm:max-w-[37.5rem]"
>
	{#if tab === 'general'}
		<Field.Field>
			<Field.Label for="field-def-name">{m.field_name()}</Field.Label>
			<Input id="field-def-name" bind:value={name} maxlength={200} required />
			{#if initial}
				<!-- The key templates use, from the saved name (a new name renames it in templates). -->
				<div class="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
					<span id="field-def-key-label">{m.field_def_key()}:</span>
					<code
						class="rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[0.8125rem] break-all text-foreground"
						aria-labelledby="field-def-key-label">{`field.${initial.key}`}</code
					>
					<InfoHint text={m.field_def_key_hint()} about={m.field_def_key()} />
				</div>
			{/if}
		</Field.Field>
		<Field.Field>
			<HintLabel for="field-def-type" label={m.field_def_type()} hint={m.field_def_hint()} />
			<Select
				id="field-def-type"
				bind:value={dataType as string}
				disabled={initial !== null}
				options={FIELD_TYPES.map((type) => ({ value: type, label: fieldTypeLabel(type) }))}
			/>
		</Field.Field>
		<Field.Field>
			<HintLabel
				for="field-def-description"
				label={m.field_def_description()}
				hint={m.field_def_description_hint()}
				hintId="field-def-description-hint"
			/>
			<Textarea
				id="field-def-description"
				bind:value={description}
				rows={3}
				maxlength={300}
				aria-describedby="field-def-description-hint"
			/>
		</Field.Field>
		<!-- Set by hand: a switch at the end of its line, as the required ones of the types. -->
		<div class="flex items-center gap-3">
			<div class="flex min-w-0 flex-1 flex-col gap-0.5">
				<div class="flex items-center gap-1">
					<span id="field-def-manual-label" class="text-sm font-medium">
						{m.field_def_manual()}
					</span>
					<InfoHint
						text={m.field_def_manual_hint()}
						about={m.field_def_manual()}
						id="field-def-manual-hint"
					/>
				</div>
				<p class="text-sm text-muted-foreground">{m.field_def_manual_line()}</p>
			</div>
			<Switch
				bind:checked={manual}
				aria-labelledby="field-def-manual-label"
				aria-describedby="field-def-manual-hint"
			/>
		</div>
		{#if isChoice}
			<Field.Field>
				<HintLabel
					for="field-def-choices"
					label={m.field_def_choices()}
					hint={m.field_def_choices_hint()}
				/>
				<Textarea id="field-def-choices" bind:value={choices} rows={4} />
			</Field.Field>
		{/if}
	{:else}
		<fieldset class="flex flex-col gap-2" aria-labelledby="field-def-scope-label">
			<div class="mb-1 flex items-center gap-1">
				<span id="field-def-scope-label" class="text-sm font-medium">{m.field_def_scope()}</span>
				<InfoHint text={m.field_def_required_hint()} about={m.field_def_scope()} />
			</div>
			<!-- Every type or certain ones, as the kind of a new tag is chosen. -->
			<div class="grid gap-2 sm:grid-cols-2">
				{#each [true, false] as every (every)}
					<label
						class={cn(
							'flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition-colors hover:bg-secondary/60',
							global === every && 'border-primary bg-primary/10 hover:bg-primary/10'
						)}
					>
						<input
							type="radio"
							name="field-def-scope"
							checked={global === every}
							onchange={() => (global = every)}
							class="size-4 shrink-0 accent-primary"
						/>
						{every ? m.field_def_scope_global() : m.field_def_scope_some()}
					</label>
				{/each}
			</div>
			{#if global}
				<div class="mt-1 flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5">
					<span id="field-def-required-label" class="text-sm">
						{m.field_def_required_everywhere()}
					</span>
					<Switch bind:checked={required} aria-labelledby="field-def-required-label" />
				</div>
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
		</fieldset>
	{/if}
</EditorShell>
