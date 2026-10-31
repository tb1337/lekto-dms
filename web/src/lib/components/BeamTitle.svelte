<script lang="ts">
	import ScanEye from '@lucide/svelte/icons/scan-eye';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// Wherever Lekto names a document, its title opens it in the Beam (web/DESIGN.md, "Beam"):
	// the eye before the title, both one button in the brand colour, one line, cut. Into the
	// document from the Beam; no title opens it directly.
	let {
		title,
		label,
		mono = false,
		disabled = false,
		class: className,
		onview
	}: {
		/** What it shows: a document's title, or the value it is found by. */
		title: string;
		/** Its name for a screen reader and the native title; by default „{title}“ ansehen. */
		label?: string;
		mono?: boolean;
		disabled?: boolean;
		class?: string;
		onview: () => void;
	} = $props();

	const name = $derived(label ?? m.beam_open_named({ title }));
</script>

<button
	type="button"
	class={cn(
		'group inline-flex min-h-6 min-w-0 items-center gap-1.5 text-left font-medium text-brand disabled:opacity-50 max-sm:min-h-11',
		className
	)}
	aria-label={name}
	title={name}
	{disabled}
	onclick={onview}
>
	<ScanEye class="size-4 shrink-0" aria-hidden="true" />
	<span class={cn('truncate underline-offset-2 group-hover:underline', mono && 'font-mono text-sm')}
		>{title}</span
	>
</button>
