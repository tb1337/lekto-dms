<script lang="ts">
	import Pencil from '@lucide/svelte/icons/pencil';
	import IconButton from '#lib/components/IconButton.svelte';
	import { cn } from '#lib/utils.ts';

	// The pencil that opens an item's editor: last in its row, in a column of its own behind a
	// line, apart from the row's other buttons, chips and counts (Tobi, 20.10.2026). Every list
	// whose items have an editor has it: master data, spaces, webhooks, rules, users. A link with
	// `href`, else a button. As a direct child of the row it is as high as the row's content.
	let {
		label,
		href,
		onclick,
		class: className = ''
	}: { label: string; href?: string; onclick?: () => void; class?: string } = $props();
</script>

<div class={cn('flex shrink-0 items-center self-stretch border-l pl-2', className)}>
	<IconButton {label} {href} {onclick}>
		<Pencil aria-hidden="true" />
	</IconButton>
</div>
