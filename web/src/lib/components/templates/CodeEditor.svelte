<script lang="ts">
	import { untrack } from 'svelte';
	import TemplateText from '#lib/components/templates/TemplateText.svelte';
	import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
	import type { EditorHandle } from '#lib/templates/codemirror.ts';
	import { TEMPLATE_NAMES, TEMPLATE_NAME_LABELS } from '#lib/templates/values.ts';
	import { cn } from '#lib/utils.ts';

	// The editor of a template, loaded on first use; until then the text shows coloured. `handle`
	// edits at the selection (inserting a value, a filter). `large`: the template editor's size.
	let {
		id,
		value = $bindable(''),
		handle = $bindable(null),
		label,
		describedBy,
		fields,
		invalid = false,
		large = false,
		autofocus = false,
		maxlength = 500,
		class: className = ''
	}: {
		id: string;
		value?: string;
		handle?: EditorHandle | null;
		label?: string;
		describedBy?: string;
		fields: readonly FieldDefinition[];
		invalid?: boolean;
		large?: boolean;
		autofocus?: boolean;
		maxlength?: number;
		class?: string;
	} = $props();

	let host = $state<HTMLDivElement | null>(null);

	$effect(() => {
		const parent = host;
		if (!parent) return;
		let stopped = false;
		let mounted: EditorHandle | null = null;
		void import('#lib/templates/codemirror.ts').then(({ mountTemplateEditor }) => {
			if (stopped) return;
			mounted = mountTemplateEditor({
				parent,
				value: untrack(() => value),
				onchange: (next) => (value = next),
				completions: () => ({
					names: TEMPLATE_NAMES.map((name) => ({ name, label: TEMPLATE_NAME_LABELS[name]() })),
					fields: fields.map((field) => ({ key: field.key, name: field.name }))
				}),
				id,
				label,
				describedBy,
				invalid: untrack(() => invalid),
				maxlength,
				autofocus
			});
			handle = mounted;
		});
		return () => {
			stopped = true;
			mounted?.destroy();
			handle = null;
		};
	});

	// A value set from outside (the template editor applied, the form reset) reaches the editor.
	$effect(() => {
		handle?.setValue(value);
	});
	$effect(() => {
		handle?.setInvalid(invalid);
	});
</script>

<div
	class={cn(
		'rounded-xl border border-input bg-card transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30',
		invalid &&
			'border-destructive ring-3 ring-destructive/20 dark:border-destructive/50 dark:ring-destructive/40',
		large ? 'min-h-40' : 'min-h-11',
		className
	)}
	data-slot="template-editor"
>
	<div bind:this={host}></div>
	{#if !handle}
		<div class="px-4 py-[0.65rem] text-sm leading-normal"><TemplateText text={value} /></div>
	{/if}
</div>
