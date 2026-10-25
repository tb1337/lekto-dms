<script lang="ts">
	import { untrack } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import CodeEditor from '#lib/components/templates/CodeEditor.svelte';
	import ReferencePicker, {
		type Reference
	} from '#lib/components/templates/ReferencePicker.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Sheet from '#lib/components/ui/sheet/index.ts';
	import { latest } from '#lib/latest.ts';
	import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import type { EditorHandle } from '#lib/templates/codemirror.ts';
	import { TEMPLATES_GUIDE } from '#lib/templates/guide.ts';
	import { FILTERS, FILTER_CHIPS, insertFilter, insertValue } from '#lib/templates/liquid.ts';
	import {
		LIST_NAMES,
		TEMPLATE_NAMES,
		TEMPLATE_NAME_LABELS,
		WEBHOOK_TEMPLATE_NAMES,
		WEBHOOK_TEMPLATE_NAME_LABELS,
		type TemplatePurpose
	} from '#lib/templates/values.ts';

	type Preview = components['schemas']['TemplatePreviewOut'];

	// The template editor, from the right: the template large, shown with a reference document;
	// its values and fields to insert with a click, each with what the document has; filters as
	// chips; the result below. "Apply" hands the template back, closing it drops the draft. The
	// editor takes the focus itself once loaded (the sheet's own would go to the first chip).
	let {
		open = $bindable(false),
		value,
		label,
		documentType = undefined,
		fields,
		maxlength = 500,
		purpose = 'rule',
		onapply
	}: {
		open?: boolean;
		value: string;
		label?: string;
		documentType?: string | null;
		fields: readonly FieldDefinition[];
		maxlength?: number;
		/** A webhook's body: more values, rendered as it is (JSON). */
		purpose?: TemplatePurpose;
		onapply: (value: string) => void;
	} = $props();

	const id = $props.id();
	let draft = $state('');
	let handle = $state<EditorHandle | null>(null);
	let reference = $state<Reference | null>(null);
	let preview = $state<Preview | null>(null);

	$effect(() => {
		if (open) draft = untrack(() => value);
	});

	// The template with the reference document, a moment after typing stops; the answer to an
	// older draft is dropped once a newer one is asked about.
	const previewed = latest();
	$effect(() => {
		if (!open) return;
		const template = draft;
		const document = reference?.id ?? null;
		const kind = documentType ?? null;
		const current = previewed();
		const timer = setTimeout(() => {
			void unwrap(
				api.POST('/api/v1/templates/preview', {
					body: { template, document_id: document, document_type_id: kind, purpose }
				})
			).then(
				(found) => {
					if (current()) preview = found;
				},
				() => {
					if (current()) preview = null;
				}
			);
		}, 300);
		return () => clearTimeout(timer);
	});

	const chips = FILTER_CHIPS.map((name) => FILTERS.find((filter) => filter.name === name)!);

	function insert(path: string) {
		handle?.edit((text, from, to) => insertValue(text, from, to, path, LIST_NAMES.has(path)));
	}

	function filter(text: string) {
		handle?.edit((current, from, to) => insertFilter(current, from, to, text));
	}

	function apply() {
		onapply(draft);
		open = false;
	}
</script>

<Sheet.Root bind:open>
	<Sheet.Content
		side="right"
		class="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-2xl"
		onOpenAutoFocus={(event) => event.preventDefault()}
	>
		<Sheet.Header class="border-b">
			<Sheet.Title>{m.template_editor()}</Sheet.Title>
			{#if label}<Sheet.Description>{label}</Sheet.Description>{/if}
		</Sheet.Header>
		<div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-4">
			<div class="flex flex-col gap-2">
				<CodeEditor
					id="{id}-template"
					bind:value={draft}
					bind:handle
					label={m.template_editor()}
					{fields}
					{maxlength}
					{purpose}
					invalid={Boolean(preview?.error)}
					large
					autofocus
				/>
				<div class="flex flex-wrap items-center gap-1">
					<span class="mr-1 text-xs text-muted-foreground">{m.template_filters()}</span>
					{#each chips as chip (chip.name)}
						<Button
							variant="outline"
							size="xs"
							class="font-mono"
							title={chip.insert}
							onclick={() => filter(chip.insert)}
						>
							{chip.name}
						</Button>
					{/each}
					<a
						href={TEMPLATES_GUIDE}
						target="_blank"
						rel="noopener noreferrer"
						class="ml-auto text-xs text-primary underline-offset-2 hover:underline"
					>
						{m.template_guide()}
					</a>
				</div>
			</div>

			<div class="flex flex-col gap-1.5">
				<span class="text-sm font-medium">{m.template_reference()}</span>
				<ReferencePicker bind:value={reference} {documentType} />
			</div>

			<section class="flex flex-col gap-1.5" aria-labelledby="{id}-values">
				<h3 id="{id}-values" class="text-sm font-medium">{m.template_values()}</h3>
				<ul class="divide-y rounded-lg border">
					{#each TEMPLATE_NAMES as name (name)}
						{@render row(name, TEMPLATE_NAME_LABELS[name]())}
					{/each}
					{#if purpose === 'webhook'}
						{#each WEBHOOK_TEMPLATE_NAMES as name (name)}
							<!-- Event and rule are only known when it happens: no value to show. -->
							{@render row(
								name,
								WEBHOOK_TEMPLATE_NAME_LABELS[name](),
								name.startsWith('event.') || name.startsWith('rule.')
							)}
						{/each}
					{/if}
				</ul>
			</section>
			{#if fields.length > 0}
				<section class="flex flex-col gap-1.5" aria-labelledby="{id}-fields">
					<h3 id="{id}-fields" class="text-sm font-medium">{m.template_fields()}</h3>
					<ul class="divide-y rounded-lg border">
						{#each fields as field (field.id)}
							{@render row(`field.${field.key}`, field.name)}
						{/each}
					</ul>
				</section>
			{/if}
		</div>
		<Sheet.Footer class="gap-3 border-t">
			<div class="min-h-5 text-sm break-words" aria-live="polite">
				{#if preview?.error}
					<span class="text-destructive">{preview.error}</span>
				{:else if !reference}
					<span class="text-muted-foreground">{m.template_preview_none()}</span>
				{:else if preview?.missing}
					<span class="text-muted-foreground">
						{m.template_missing({ title: reference.title, value: preview.missing })}
					</span>
				{:else if preview?.rendered !== undefined && preview?.rendered !== null}
					<span class="text-muted-foreground">{m.template_preview({ title: reference.title })}</span
					>
					{#if purpose === 'webhook'}
						<pre
							class="mt-1 max-h-48 overflow-auto rounded-lg border bg-secondary p-2 font-mono text-xs whitespace-pre-wrap">{preview.rendered}</pre>
					{:else}
						<span class="font-medium">{preview.rendered}</span>
					{/if}
				{/if}
			</div>
			<div class="flex justify-end gap-2">
				<Button variant="outline" onclick={() => (open = false)}>{m.cancel()}</Button>
				<Button onclick={apply}>{m.template_editor_apply()}</Button>
			</div>
		</Sheet.Footer>
	</Sheet.Content>
</Sheet.Root>

{#snippet row(path: string, name: string, unknown = false)}
	{@const shown = preview?.values && !unknown ? (preview.values[path] ?? null) : undefined}
	<li>
		<button
			type="button"
			class="grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 px-3 py-1.5 text-left text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none sm:grid-cols-[9rem_minmax(0,11rem)_minmax(0,1fr)]"
			aria-label={m.template_insert({ name })}
			onclick={() => insert(path)}
		>
			<span class="truncate">{name}</span>
			<span class="tpl-variable truncate font-mono text-xs">{path}</span>
			{#if shown !== undefined}
				<span
					class="col-span-2 truncate text-muted-foreground sm:col-span-1 {shown === null
						? 'italic'
						: ''}"
				>
					{shown ?? m.template_no_value()}
				</span>
			{/if}
		</button>
	</li>
{/snippet}
