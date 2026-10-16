<script lang="ts">
	import Workflow from '@lucide/svelte/icons/workflow';
	import AssignmentList, { type Assignment } from '#lib/components/AssignmentList.svelte';
	import MultiPicker from '#lib/components/MultiPicker.svelte';
	import NativeSelect from '#lib/components/NativeSelect.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import IdentifiersEditor from '#lib/components/IdentifiersEditor.svelte';
	import TemplateInput from '#lib/components/templates/TemplateInput.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { changesOf, type IdentifierRow, rowsOf } from '#lib/identifiers.ts';
	import { type Extra, type Item, parseAliases, type Values } from '#lib/masterdata-api.ts';
	import type { FieldDefinition, Tag, TagScope } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { below, ofScope, pathLabel, tagOptions } from '#lib/tags.ts';

	// Create or change a contact (name, aliases, identifiers, groups), a document type (name,
	// description, title pattern, fields, groups) or a tag (name, parent of its scope, how it is
	// set, whether documents show it). The API decides what is valid; its answer (e.g. 409 for
	// a taken name) shows below.
	let {
		open = $bindable(false),
		title,
		extra,
		initial = null,
		submitLabel = m.save(),
		ruleHref = null,
		fields = null,
		tags = [],
		scope = null,
		onsubmit
	}: {
		open?: boolean;
		title: string;
		extra: Extra;
		initial?: Item | null;
		submitLabel?: string;
		/** The rule of the type's title pattern, to go to from here. */
		ruleHref?: string | null;
		/** Every field, for a document type's: those of the type are assigned there. */
		fields?: readonly FieldDefinition[] | null;
		/** Every tag: parents of a tag, groups of a contact or type. */
		tags?: readonly Tag[];
		/** The scope of a tag. */
		scope?: TagScope | null;
		onsubmit: (values: Values) => Promise<void>;
	} = $props();

	let name = $state('');
	let aliases = $state('');
	let identifiers = $state<IdentifierRow[]>([]);
	let description = $state('');
	let titlePattern = $state('');
	let assigned = $state<Assignment[]>([]);
	let groupIds = $state<string[]>([]);
	let parentId = $state('');
	let manual = $state(false);
	let shown = $state(true);
	let error = $state<string | null>(null);
	const groupScope = $derived<TagScope | null>(
		extra === 'aliases' ? 'contact' : extra === 'description' ? 'document_type' : null
	);
	const isGroup = $derived(scope !== null && scope !== 'document');
	// A tag goes under one of its scope, never under itself or one below it.
	const parents = $derived.by(() => {
		if (scope === null) return [];
		const own = initial?.id;
		const excluded = own ? below(tags, own).add(own) : new Set<string>();
		return ofScope(tags, scope)
			.filter((tag) => !excluded.has(tag.id))
			.map((tag) => ({ value: tag.id, label: pathLabel(tag) }));
	});
	const typed = $derived((fields ?? []).filter((field) => field.document_type_ids !== null));
	const everywhere = $derived((fields ?? []).filter((field) => field.document_type_ids === null));
	let busy = $state(false);

	$effect(() => {
		if (open) {
			name = initial?.name ?? '';
			aliases = (initial?.aliases ?? []).join('\n');
			identifiers = rowsOf(initial?.identifiers);
			description = initial?.description ?? '';
			titlePattern = initial?.title_pattern ?? '';
			groupIds = [...(initial?.group_ids ?? [])];
			parentId = initial?.parent_id ?? '';
			manual = initial?.assignment === 'manual';
			shown = initial?.shown ?? (scope === null || scope === 'document');
			const id = initial?.id;
			assigned = id
				? typed
						.filter((field) => field.document_type_ids?.includes(id))
						.map((field) => ({
							id: field.id,
							required: field.required_document_type_ids.includes(id)
						}))
				: [];
			error = null;
		}
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		busy = true;
		error = null;
		try {
			await onsubmit({
				name: name.trim(),
				aliases: parseAliases(aliases),
				...changesOf(identifiers),
				description: description.trim() || null,
				title_pattern: titlePattern.trim() || null,
				fields: extra === 'description' && fields ? assigned : null,
				group_ids: groupIds,
				parent_id: parentId || null,
				assignment: manual ? 'manual' : 'auto',
				shown
			});
			open = false;
		} catch (problem) {
			error = describeError(problem);
		} finally {
			busy = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="max-w-lg sm:max-w-xl">
		<form class="flex flex-col gap-4" onsubmit={submit} novalidate>
			<Dialog.Header><Dialog.Title>{title}</Dialog.Title></Dialog.Header>
			<Field.Field>
				<Field.Label for="master-name">{m.field_name()}</Field.Label>
				<Input id="master-name" bind:value={name} maxlength={200} required />
			</Field.Field>
			{#if extra === 'tag' && scope !== null}
				<Field.Field>
					<Field.Label for="master-parent">
						{isGroup ? m.tag_parent_group() : m.tag_parent()}
					</Field.Label>
					<NativeSelect
						id="master-parent"
						bind:value={parentId}
						options={[{ value: '', label: m.tag_parent_none() }, ...parents]}
						class="h-10"
					/>
				</Field.Field>
				{#if !isGroup}
					<fieldset class="flex flex-col gap-2">
						<legend class="mb-2 text-sm font-medium">{m.tag_assignment()}</legend>
						<div class="flex flex-wrap gap-x-6 gap-y-2">
							<label class="flex items-center gap-2 text-sm">
								<input
									type="radio"
									name="master-assignment"
									checked={!manual}
									onchange={() => (manual = false)}
									class="size-4 accent-primary"
								/>
								{m.tag_assignment_auto()}
							</label>
							<label class="flex items-center gap-2 text-sm">
								<input
									type="radio"
									name="master-assignment"
									checked={manual}
									onchange={() => (manual = true)}
									class="size-4 accent-primary"
								/>
								{m.tag_assignment_manual()}
							</label>
						</div>
						<Field.Description>{m.tag_assignment_hint()}</Field.Description>
					</fieldset>
				{/if}
				<Field.Field>
					<label class="flex items-center gap-2 text-sm font-medium">
						<input
							type="checkbox"
							bind:checked={shown}
							class="size-4 accent-primary"
							aria-describedby="master-shown-hint"
						/>
						{m.tag_shown()}
					</label>
					<Field.Description id="master-shown-hint">
						{isGroup ? m.tag_group_shown_hint() : m.tag_shown_hint()}
					</Field.Description>
				</Field.Field>
			{/if}
			{#if groupScope !== null}
				<Field.Field>
					<Field.Label for="master-groups">{m.master_groups()}</Field.Label>
					<MultiPicker
						id="master-groups"
						label={m.master_groups()}
						options={tagOptions(tags, groupScope)}
						selected={groupIds}
						onchange={(next) => (groupIds = next)}
					/>
					<Field.Description>
						{groupScope === 'contact'
							? m.master_contact_groups_hint()
							: m.master_type_groups_hint()}
					</Field.Description>
				</Field.Field>
			{/if}
			{#if extra === 'aliases'}
				<Field.Field>
					<Field.Label for="master-aliases">{m.master_aliases()}</Field.Label>
					<Textarea id="master-aliases" bind:value={aliases} rows={4} />
					<Field.Description>{m.master_aliases_hint()}</Field.Description>
				</Field.Field>
				<Field.Field>
					<Field.Label>{m.master_identifiers()}</Field.Label>
					<IdentifiersEditor bind:rows={identifiers} />
					<Field.Description>{m.master_identifiers_hint()}</Field.Description>
				</Field.Field>
			{:else if extra === 'description'}
				<Field.Field>
					<Field.Label for="master-description">{m.master_description()}</Field.Label>
					<Textarea id="master-description" bind:value={description} rows={3} maxlength={300} />
					<Field.Description>{m.master_description_hint()}</Field.Description>
				</Field.Field>
				<Field.Field>
					<Field.Label for="master-title-pattern">{m.master_title_pattern()}</Field.Label>
					<TemplateInput
						id="master-title-pattern"
						bind:value={titlePattern}
						label={m.master_title_pattern()}
						documentType={initial?.id ?? null}
					/>
					<Field.Description>{m.master_title_pattern_hint()}</Field.Description>
					{#if ruleHref}
						<a
							href={ruleHref}
							class="inline-flex items-center gap-1 self-start text-sm text-brand hover:underline"
							onclick={() => (open = false)}
						>
							<Workflow class="size-3.5" aria-hidden="true" />
							{m.master_title_rule()}
						</a>
					{/if}
				</Field.Field>
				{#if fields}
					<Field.Field>
						<Field.Label>{m.master_type_fields()}</Field.Label>
						<AssignmentList
							{assigned}
							candidates={typed.map((field) => ({
								id: field.id,
								name: field.name,
								hint: `field.${field.key}`
							}))}
							label={m.master_type_fields()}
							addLabel={m.master_type_add_field()}
							emptyLabel={m.master_type_no_fields()}
							onchange={(items) => (assigned = items)}
						/>
						{#if everywhere.length > 0}
							<Field.Description>
								{m.master_type_global_fields({
									fields: everywhere.map((field) => field.name).join(', ')
								})}
							</Field.Description>
						{/if}
					</Field.Field>
				{/if}
			{/if}
			{#if error}<p class="text-sm text-destructive" role="alert">{error}</p>{/if}
			<Dialog.Footer>
				<Button type="button" variant="ghost" onclick={() => (open = false)}>{m.cancel()}</Button>
				<Button type="submit" disabled={busy || name.trim() === ''}>{submitLabel}</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
