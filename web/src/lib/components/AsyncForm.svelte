<script lang="ts">
	import type { Snippet } from 'svelte';
	import { describeError } from '#lib/errors.ts';

	// A form whose submit runs `action` (a request): busy meanwhile (a second submit does
	// nothing), `ondone` once it resolves (the dialog closes), the error described when it
	// throws. `children` get both, for the buttons and the error line. In a dialog the form is
	// made anew each time the dialog opens, so nothing is left over from the last time.
	let {
		action,
		ondone,
		class: className,
		onchanged,
		children
	}: {
		action: () => Promise<void>;
		ondone: () => void;
		class?: string;
		/** Something in the form was typed or chosen (for a question before leaving). */
		onchanged?: () => void;
		children: Snippet<[{ busy: boolean; error: string | null }]>;
	} = $props();

	let busy = $state(false);
	let error = $state<string | null>(null);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		busy = true;
		error = null;
		try {
			await action();
			ondone();
		} catch (problem) {
			error = describeError(problem);
		} finally {
			busy = false;
		}
	}
</script>

<form class={className} onsubmit={submit} oninput={onchanged} onchange={onchanged} novalidate>
	{@render children({ busy, error })}
</form>
