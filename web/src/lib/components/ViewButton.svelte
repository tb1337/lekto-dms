<script lang="ts">
	import ScanEye from '@lucide/svelte/icons/scan-eye';
	import IconButton from '#lib/components/IconButton.svelte';
	import { m } from '#lib/paraglide/messages.js';

	// Opens a document in the Beam (web/DESIGN.md, "Beam"): "Ansehen", an icon at the end of a
	// row or beside a title.
	let {
		title,
		class: className,
		onclick
	}: { title: string; class?: string; onclick: () => void } = $props();
</script>

<IconButton
	size="sm"
	label={m.beam_open_named({ title })}
	hint={m.beam_open()}
	class={className}
	{onclick}
>
	<ScanEye aria-hidden="true" />
</IconButton>
