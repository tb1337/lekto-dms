<script lang="ts">
	import ScanEye from '@lucide/svelte/icons/scan-eye';
	import IconButton from '#lib/components/IconButton.svelte';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// Opens a document in the Beam (web/DESIGN.md, "Beam"): "Ansehen". `pill` on a card's first
	// page, as glass with its name; else an icon at the end of a row or beside a title.
	let {
		title,
		pill = false,
		class: className,
		onclick
	}: { title: string; pill?: boolean; class?: string; onclick: () => void } = $props();
</script>

{#if pill}
	<button
		type="button"
		class={cn(
			'mark-glass relative inline-flex h-7 items-center gap-1.5 rounded-full border bg-card/85 pr-2.5 pl-2 text-xs font-medium text-foreground hover:bg-card max-sm:after:absolute max-sm:after:-inset-2',
			className
		)}
		aria-label={m.beam_open_named({ title })}
		{onclick}
	>
		<ScanEye class="size-3.5" aria-hidden="true" />
		{m.beam_open()}
	</button>
{:else}
	<IconButton
		size="sm"
		label={m.beam_open_named({ title })}
		hint={m.beam_open()}
		class={className}
		{onclick}
	>
		<ScanEye aria-hidden="true" />
	</IconButton>
{/if}
