<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import { m } from '#lib/paraglide/messages.js';

	// What a picker offers an admin for a search that finds no tag of its kind named so:
	// "„…“ anlegen …", the tag dialog with the name filled in.
	let { name, onclick }: { name: string; onclick: () => void } = $props();
</script>

<button
	type="button"
	class="flex min-h-12 w-full shrink-0 items-center gap-2.5 rounded-2xl bg-panel px-3.5 text-left font-medium text-brand hover:bg-brand/10"
	{onclick}
>
	<Plus class="size-4 shrink-0" aria-hidden="true" />
	<span class="min-w-0 break-words">{m.create_named({ name })}</span>
</button>
