<script lang="ts">
	import InfoHint from '#lib/components/InfoHint.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';

	// A field's label with its help behind an info button (`InfoHint`). `for` ties the label to
	// its control; `id` names the label for a control labelled by it; `hintId` names the help for
	// the control's `aria-describedby`.
	let {
		label,
		hint,
		for: htmlFor,
		id,
		hintId
	}: { label: string; hint: string; for?: string; id?: string; hintId?: string } = $props();
</script>

<div class="flex items-center gap-1">
	<Field.Label for={htmlFor} {id}>{label}</Field.Label>
	<InfoHint text={hint} about={label} id={hintId} />
</div>
