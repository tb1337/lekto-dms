<script lang="ts">
	import ConfirmFooter from '#lib/components/ConfirmFooter.svelte';
	import * as AlertDialog from '#lib/components/ui/alert-dialog/index.ts';
	import { reportError } from '#lib/errors.ts';

	// Asks before a destructive action. The action runs on confirm; the dialog closes when it
	// succeeds and stays open (with the error as a toast) when it fails.
	let {
		open = $bindable(false),
		title,
		description,
		confirmLabel,
		destructive = true,
		onconfirm
	}: {
		open?: boolean;
		title: string;
		description: string;
		confirmLabel: string;
		destructive?: boolean;
		onconfirm: () => Promise<void>;
	} = $props();

	let busy = $state(false);

	async function confirm(event: Event) {
		event.preventDefault();
		busy = true;
		try {
			await onconfirm();
			open = false;
		} catch (error) {
			reportError(error);
		} finally {
			busy = false;
		}
	}
</script>

<AlertDialog.Root bind:open>
	<AlertDialog.Content>
		<AlertDialog.Header>
			<AlertDialog.Title>{title}</AlertDialog.Title>
			<AlertDialog.Description>{description}</AlertDialog.Description>
		</AlertDialog.Header>
		<ConfirmFooter label={confirmLabel} {busy} {destructive} onconfirm={confirm} />
	</AlertDialog.Content>
</AlertDialog.Root>
