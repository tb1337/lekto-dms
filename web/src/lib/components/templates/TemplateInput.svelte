<script lang="ts">
	import Braces from '@lucide/svelte/icons/braces';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import CodeEditor from '#lib/components/templates/CodeEditor.svelte';
	import TemplateEditor from '#lib/components/templates/TemplateEditor.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { latest } from '#lib/latest.ts';
	import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { usableFields, type TemplatePurpose } from '#lib/templates/values.ts';

	// A template (Liquid) of a rule or a title pattern in a small field: coloured, with completion
	// after `{{`, `{%` and `|`, red with the reason when the server finds it invalid, and a button
	// to the template editor. `documentType`: undefined for a rule (every field), null for a type
	// not saved yet (the fields for every type, and `extraFields`: those it is created with),
	// else that type's fields. `fields` are the field definitions where the page holds them
	// already (a rule's lookup); without them they are fetched once.
	let {
		id,
		value = $bindable(''),
		label,
		documentType = undefined,
		extraFields = [],
		fields: given = undefined,
		invalid = false,
		maxlength = 500,
		purpose = 'rule',
		steps = []
	}: {
		id: string;
		value?: string;
		label?: string;
		documentType?: string | null;
		/** Ids of fields the template may use besides `documentType`'s. */
		extraFields?: readonly string[];
		/** Every field definition, when the page has them; fetched otherwise. */
		fields?: readonly FieldDefinition[];
		invalid?: boolean;
		maxlength?: number;
		/** A webhook's body: more values, rendered as it is, and it has to make JSON. */
		purpose?: TemplatePurpose;
		/** A rule's step: the names of the steps before it that ask (`steps.<name>`). */
		steps?: readonly string[];
	} = $props();

	let loaded = $state<FieldDefinition[]>([]);
	let error = $state<string | null>(null);
	let editing = $state(false);

	const fields = $derived(given ?? loaded);
	const usable = $derived(
		fields.filter(
			(field) => usableFields([field], documentType).length > 0 || extraFields.includes(field.id)
		)
	);

	// The fields, unless given; an answer after the field is gone changes nothing.
	$effect(() => {
		if (given) return;
		let current = true;
		void unwrap(api.GET('/api/v1/fields')).then(
			(found) => {
				if (current) loaded = found;
			},
			() => {
				if (current) loaded = [];
			}
		);
		return () => {
			current = false;
		};
	});

	// The server's check, a moment after typing stops; the answer to an older template is
	// dropped once a newer one is asked about.
	const checked = latest();
	$effect(() => {
		const template = value.trim();
		const kind = documentType ?? null;
		const current = checked();
		if (!template) {
			error = null;
			return;
		}
		const timer = setTimeout(() => {
			void unwrap(
				api.POST('/api/v1/templates/preview', {
					body: { template, document_type_id: kind, purpose }
				})
			).then(
				(found) => {
					if (current()) error = found.error ?? null;
				},
				() => {
					if (current()) error = null;
				}
			);
		}, 400);
		return () => clearTimeout(timer);
	});
</script>

<div class="flex flex-col gap-1.5">
	<div class="flex items-start gap-1">
		<CodeEditor
			{id}
			bind:value
			{label}
			reason={error}
			fields={usable}
			invalid={invalid || error !== null}
			{maxlength}
			{purpose}
			{steps}
			class="min-w-0 flex-1"
		/>
		<Button
			variant="ghost"
			size="icon"
			class="shrink-0"
			aria-label={m.template_editor_open()}
			title={m.template_editor_open()}
			onclick={() => (editing = true)}
		>
			<Braces aria-hidden="true" />
		</Button>
	</div>
	<p class="text-sm text-destructive" class:hidden={!error} aria-live="polite">
		{error ?? ''}
	</p>
</div>

<TemplateEditor
	bind:open={editing}
	{value}
	{label}
	{documentType}
	fields={usable}
	{maxlength}
	{purpose}
	{steps}
	onapply={(next) => (value = next)}
/>
