<script lang="ts">
	import type { Snippet } from 'svelte';
	import { goto } from '$app/navigation';
	import { cn } from '#lib/utils.ts';
	import { viewOrOpen } from '#lib/view-or-open.ts';

	// The part of a document's card or row that opens it (web/DESIGN.md, "Beam"): with `onview` a
	// click, a tap or Enter shows the document in the Beam, a double click or a long press opens
	// it (`viewOrOpen`); a new tab works as on any link. With `onchoose` (the selection mode of a
	// list) it is no link but the label of the box it holds: a tap chooses it.
	let {
		href,
		choosing = false,
		onview,
		class: className,
		children
	}: {
		href: string;
		choosing?: boolean;
		onview?: () => void;
		class?: string;
		children: Snippet;
	} = $props();

	const viewing = $derived(onview !== undefined && !choosing);
</script>

<svelte:element
	this={choosing ? 'label' : 'a'}
	href={choosing ? undefined : href}
	aria-haspopup={viewing ? 'dialog' : undefined}
	class={cn(
		className,
		choosing && 'cursor-pointer',
		viewing && 'select-none [-webkit-touch-callout:none]'
	)}
	{@attach viewing && onview && viewOrOpen(onview, () => goto(href))}
>
	{@render children()}
</svelte:element>
