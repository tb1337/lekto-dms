<script lang="ts">
	import HintLabel from '#lib/components/HintLabel.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import { describeError } from '#lib/errors.ts';
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
	let error = $state<string | null>(null);
	let busy = $state(false);

	$effect(() => {
		if (open) {
			name = initialName;
			description = initialDescription;
			error = null;
		}
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		busy = true;
		error = null;
		try {
			await onsubmit(name.trim(), description.trim());
			open = false;
		} catch (problem) {
			error = describeError(problem);
		} finally {
			busy = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content>
		<form class="flex flex-col gap-4" onsubmit={submit} novalidate>
			<Dialog.Header><Dialog.Title>{title}</Dialog.Title></Dialog.Header>
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
			{#if error}<Field.Error>{error}</Field.Error>{/if}
			<Dialog.Footer>
				<Button type="button" variant="ghost" onclick={() => (open = false)}>{m.cancel()}</Button>
				<Button type="submit" disabled={busy || (named && name.trim() === '')}>
					{submitLabel}
				</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
