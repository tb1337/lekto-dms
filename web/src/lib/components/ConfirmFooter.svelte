<script lang="ts">
	import * as AlertDialog from '#lib/components/ui/alert-dialog/index.ts';
	import { buttonVariants } from '#lib/components/ui/button/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// The footer of a dialog that asks before an action: "Cancel" and the action, both held while
	// the action runs (`busy`), the action also while the choice is not complete (`disabled`).
	let {
		label,
		busy = false,
		disabled = false,
		destructive = true,
		onconfirm
	}: {
		label: string;
		busy?: boolean;
		disabled?: boolean;
		destructive?: boolean;
		onconfirm: (event: Event) => void;
	} = $props();
</script>

<AlertDialog.Footer>
	<AlertDialog.Cancel disabled={busy}>{m.cancel()}</AlertDialog.Cancel>
	<AlertDialog.Action
		disabled={busy || disabled}
		onclick={onconfirm}
		class={cn(destructive && buttonVariants({ variant: 'destructive' }))}
	>
		{label}
	</AlertDialog.Action>
</AlertDialog.Footer>
