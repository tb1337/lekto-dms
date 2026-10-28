<script lang="ts">
	import type { Snippet } from 'svelte';
	import AsyncForm from '#lib/components/AsyncForm.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import { describeError } from '#lib/errors.ts';

	// A short form in a dialog (a space, a webhook, a code, a token): its title, the fields
	// (`children`, told the error for `aria-invalid`), what the API answered below them, and
	// "Cancel" before the submit button. On a phone it fills the screen with the bar of every
	// editor ("Cancel" · title · submit; web/DESIGN.md, "Dialogs"). `action` runs on submit; the dialog is busy meanwhile,
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
		ondelete,
		deleteTitle = '',
		deleteDescription = '',
		alternative,
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
		/** Deleting what the dialog edits: asked first, in the footer as the editors have it. */
		ondelete?: () => Promise<void>;
		deleteTitle?: string;
		deleteDescription?: string;
		/** A second way to finish, at the start of the footer, without asking (an open
		 * identifier: rejecting it beside confirming it). */
		alternative?: { label: string; action: () => Promise<void> };
		children: Snippet<[string | null]>;
	} = $props();

	let confirming = $state(false);
	let altBusy = $state(false);
	let altError = $state<string | null>(null);

	$effect(() => {
		if (open) altError = null;
	});

	async function runAlternative() {
		if (!alternative || altBusy) return;
		altBusy = true;
		altError = null;
		try {
			await alternative.action();
			open = false;
		} catch (problem) {
			altError = describeError(problem);
		} finally {
			altBusy = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content
		size="md"
		showCloseButton={!phone.current}
		class={cn(
			phone.current &&
				'top-0 left-0 flex h-dvh max-h-dvh w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-0 bg-background p-0',
			className
		)}
	>
		<AsyncForm
			class={cn('flex flex-col gap-4', phone.current && 'min-h-0 flex-1 gap-0')}
			{action}
			ondone={() => (open = false)}
		>
			{#snippet children({ busy, error })}
				{#if phone.current}
					<!-- On a phone the editor pattern of web/DESIGN.md: full screen, a bar on top. -->
					<div
						class="grid h-14 shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-1 border-b bg-card px-1"
					>
						<Button
							type="button"
							variant="ghost"
							class="h-11 justify-self-start px-3 text-base font-normal text-brand"
							onclick={() => (open = false)}
						>
							{m.cancel()}
						</Button>
						<Dialog.Title class="max-w-[50vw] truncate text-base font-semibold"
							>{title}</Dialog.Title
						>
						<Button
							type="submit"
							variant="ghost"
							class={cn(
								'h-11 justify-self-end px-3 text-base font-semibold',
								destructive ? 'text-destructive' : 'text-brand'
							)}
							disabled={busy || disabled}
						>
							{submitLabel}
						</Button>
					</div>
					<div class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain p-4">
						{#if description}<p class="text-sm text-muted-foreground">{description}</p>{/if}
						{@render fields(error)}
						{#if error ?? altError}<Field.Error>{error ?? altError}</Field.Error>{/if}
						{#if alternative}
							<Button
								type="button"
								variant="outline"
								class="mt-2"
								disabled={busy || altBusy}
								onclick={runAlternative}
							>
								{alternative.label}
							</Button>
						{/if}
						{#if ondelete}
							<Button
								type="button"
								variant="outline"
								class="mt-2 text-destructive"
								onclick={() => (confirming = true)}
							>
								<Trash2 aria-hidden="true" />
								{deleteTitle}
							</Button>
						{/if}
					</div>
				{:else}
					<Dialog.Header>
						<Dialog.Title>{title}</Dialog.Title>
						{#if description}<Dialog.Description>{description}</Dialog.Description>{/if}
					</Dialog.Header>
					{@render fields(error)}
					{#if error ?? altError}<Field.Error>{error ?? altError}</Field.Error>{/if}
					<Dialog.Footer>
						{#if alternative}
							<Button
								type="button"
								variant="outline"
								class="sm:mr-auto"
								disabled={busy || altBusy}
								onclick={runAlternative}
							>
								{alternative.label}
							</Button>
						{/if}
						{#if ondelete}
							<Button
								type="button"
								variant="ghost"
								class="text-destructive hover:text-destructive sm:mr-auto"
								aria-label={deleteTitle}
								onclick={() => (confirming = true)}
							>
								<Trash2 aria-hidden="true" />
								{m.delete_title()}
							</Button>
						{/if}
						<Button type="button" variant="ghost" onclick={() => (open = false)}
							>{m.cancel()}</Button
						>
						<Button
							type="submit"
							variant={destructive ? 'destructive' : 'default'}
							disabled={busy || altBusy || disabled}
						>
							{submitLabel}
						</Button>
					</Dialog.Footer>
				{/if}
			{/snippet}
		</AsyncForm>
	</Dialog.Content>
</Dialog.Root>

{#if ondelete}
	<ConfirmDialog
		bind:open={confirming}
		title={deleteTitle}
		description={deleteDescription}
		confirmLabel={m.delete_title()}
		onconfirm={async () => {
			await ondelete();
			open = false;
		}}
	/>
{/if}
