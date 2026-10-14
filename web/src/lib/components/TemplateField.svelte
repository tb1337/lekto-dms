<script lang="ts">
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { PLACEHOLDER_LABELS } from '#lib/rules/describe.ts';
	import { TEMPLATE_VALUES, fieldTemplate, templateValue } from '#lib/rules/model.ts';

	type Preview = components['schemas']['TemplatePreviewOut'];

	// A template (Liquid) of a rule or a title pattern: the text in a fixed-pitch font, the
	// values and fields to insert with a click, and what the server says of it, rendered with a
	// document of the type where there is one. `documentType`: undefined for a rule (every
	// field), null for a type not saved yet (global fields), else that type's fields.
	let {
		id,
		value = $bindable(''),
		documentType = undefined,
		label,
		invalid = false,
		maxlength = 500
	}: {
		id: string;
		value?: string;
		documentType?: string | null;
		label?: string;
		invalid?: boolean;
		maxlength?: number;
	} = $props();

	let input = $state<HTMLTextAreaElement | null>(null);
	let fields = $state<FieldDefinition[]>([]);
	let sample = $state<{ id: string; title: string } | null>(null);
	let preview = $state<Preview | null>(null);

	const usable = $derived(
		fields.filter(
			(field) =>
				documentType === undefined ||
				field.document_type_ids === null ||
				(documentType !== null && field.document_type_ids.includes(documentType))
		)
	);

	$effect(() => {
		void unwrap(api.GET('/api/v1/fields')).then(
			(found) => (fields = found),
			() => (fields = [])
		);
	});

	// A document of the type to render the template with: the newest one the user may read.
	$effect(() => {
		const kind = documentType;
		sample = null;
		if (!kind) return;
		void unwrap(
			api.GET('/api/v1/documents', { params: { query: { document_type_id: kind, limit: 1 } } })
		).then(
			(page) =>
				(sample = page.items[0] ? { id: page.items[0].id, title: page.items[0].title } : null),
			() => (sample = null)
		);
	});

	// What the server says, a moment after typing stops.
	$effect(() => {
		const template = value.trim();
		const document = sample?.id ?? null;
		const kind = documentType ?? null;
		if (!template) {
			preview = null;
			return;
		}
		const timer = setTimeout(() => {
			void unwrap(
				api.POST('/api/v1/templates/preview', {
					body: { template, document_id: document, document_type_id: kind }
				})
			).then(
				(found) => (preview = found),
				() => (preview = null)
			);
		}, 400);
		return () => clearTimeout(timer);
	});

	function insert(text: string) {
		const at = input?.selectionStart ?? value.length;
		const end = input?.selectionEnd ?? at;
		value = value.slice(0, at) + text + value.slice(end);
		const cursor = at + text.length;
		requestAnimationFrame(() => {
			input?.focus();
			input?.setSelectionRange(cursor, cursor);
		});
	}
</script>

<div class="flex flex-col gap-2">
	<Textarea
		{id}
		bind:ref={input}
		bind:value
		rows={2}
		{maxlength}
		aria-label={label}
		aria-invalid={invalid || preview?.error ? true : undefined}
		aria-describedby="{id}-preview"
		spellcheck="false"
		class="min-h-10 font-mono text-sm"
	/>
	<div class="flex flex-wrap items-center gap-1.5 text-sm">
		<span class="text-muted-foreground">{m.rule_insert()}</span>
		{#each TEMPLATE_VALUES as name (name)}
			<Button
				variant="outline"
				size="sm"
				class="h-7"
				title={templateValue(name)}
				onclick={() => insert(templateValue(name))}
			>
				{PLACEHOLDER_LABELS[name]()}
			</Button>
		{/each}
		{#each usable as field (field.id)}
			<Button
				variant="outline"
				size="sm"
				class="h-7 font-mono text-xs"
				title={field.name}
				onclick={() => insert(fieldTemplate(field.key))}
			>
				{`field.${field.key}`}
			</Button>
		{/each}
	</div>
	<p id="{id}-preview" class="text-sm" aria-live="polite">
		{#if preview?.error}
			<span class="text-destructive">{preview.error}</span>
		{:else if preview?.missing && sample}
			<span class="text-muted-foreground">
				{m.template_missing({ title: sample.title, value: preview.missing })}
			</span>
		{:else if preview?.rendered && sample}
			<span class="text-muted-foreground">{m.template_preview({ title: sample.title })}</span>
			<span class="font-medium">{preview.rendered}</span>
		{/if}
	</p>
</div>
