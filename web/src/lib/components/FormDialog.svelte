<script lang="ts">
	import type { Snippet } from 'svelte';
	import AsyncForm from '#lib/components/AsyncForm.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A short form in a dialog (a space, a webhook, a code, a token): its title, the fields
	// (`children`, told the error for `aria-invalid`), what the API answered below them, and
	// "Cancel" beside the submit button. `action` runs on submit; the dialog is busy meanwhile,
	// closes when it resolves and stays open with the error when it throws.
	let {
		open = $bindable(false),
		title,
		description,
		submitLabel,
		disabled = false,
		destructive = false,
		class: className,
		action,
		children: fields
	}: {
		open?: boolean;
		title: string;
		description?: string;
		submitLabel: string;
		/** Submitting is not possible yet (a name is missing). */
		disabled?: boolean;
		destructive?: boolean;
		/** The width of the dialog. */
		class?: string;
		action: () => Promise<void>;
		children: Snippet<[string | null]>;
	} = $props();
</script>

<Dialog.Root bind:open>
	<Dialog.Content class={className}>
		<AsyncForm class="flex flex-col gap-4" {action} ondone={() => (open = false)}>
			{#snippet children({ busy, error })}
				<Dialog.Header>
					<Dialog.Title>{title}</Dialog.Title>
					{#if description}<Dialog.Description>{description}</Dialog.Description>{/if}
				</Dialog.Header>
				{@render fields(error)}
				{#if error}<Field.Error>{error}</Field.Error>{/if}
				<Dialog.Footer>
					<Button type="button" variant="ghost" onclick={() => (open = false)}>{m.cancel()}</Button>
					<Button
						type="submit"
						variant={destructive ? 'destructive' : 'default'}
						disabled={busy || disabled}
					>
						{submitLabel}
					</Button>
				</Dialog.Footer>
			{/snippet}
		</AsyncForm>
	</Dialog.Content>
</Dialog.Root>
