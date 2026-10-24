<script lang="ts">
	import FormDialog from '#lib/components/FormDialog.svelte';
	import HintLabel from '#lib/components/HintLabel.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import { m } from '#lib/paraglide/messages.js';

	// Create a space or change one: its name (not of a personal space, `named` false) and the
	// description the language model reads when it suggests a space. The API decides what a valid
	// name is; its answer (e.g. 409 for a taken name) shows under the dialog.
	let {
		open = $bindable(false),
		title,
		initialName = '',
		initialDescription = '',
		named = true,
		submitLabel = m.save(),
		onsubmit
	}: {
		open?: boolean;
		title: string;
		initialName?: string;
		initialDescription?: string;
		named?: boolean;
		submitLabel?: string;
		onsubmit: (name: string, description: string) => Promise<void>;
	} = $props();

	let name = $state('');
	let description = $state('');

	$effect(() => {
		if (open) {
			name = initialName;
			description = initialDescription;
		}
	});
</script>

<FormDialog
	bind:open
	{title}
	{submitLabel}
	disabled={named && name.trim() === ''}
	action={() => onsubmit(name.trim(), description.trim())}
>
	{#snippet children(error)}
		{#if named}
			<Field.Field>
				<Field.Label for="space-dialog-name">{m.field_name()}</Field.Label>
				<Input
					id="space-dialog-name"
					bind:value={name}
					maxlength={200}
					required
					aria-invalid={error ? true : undefined}
				/>
			</Field.Field>
		{/if}
		<Field.Field>
			<HintLabel
				for="space-dialog-description"
				label={m.space_description()}
				hint={m.space_description_hint()}
				hintId="space-dialog-description-hint"
			/>
			<Textarea
				id="space-dialog-description"
				bind:value={description}
				rows={3}
				maxlength={300}
				aria-describedby="space-dialog-description-hint"
			/>
		</Field.Field>
	{/snippet}
</FormDialog>
