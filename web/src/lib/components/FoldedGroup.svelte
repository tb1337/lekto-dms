<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.ts';

	// A folded group (web/DESIGN.md, "Lists"): rows that belong to a card but rarely matter,
	// folded away at its end. A line above, then one button the width of the card with a
	// chevron turned down when open, the `count` in words and below it what they are (`hint`).
	// Closed at first; the rows inside (`children`) are indented to the button's text.
	let {
		open = $bindable(false),
		count,
		hint,
		class: className,
		children
	}: {
		open?: boolean;
		/** How many are folded, in words ("3 weitere Nummern"). */
		count: string;
		/** What they are. */
		hint: string;
		class?: string;
		children: Snippet;
	} = $props();

	const id = $props.id();
</script>

<div class={cn('border-t pt-1.5', className)}>
	<button
		type="button"
		class="flex min-h-11 w-full items-center gap-2 rounded-xl px-2.5 text-left hover:bg-panel"
		aria-expanded={open}
		aria-controls="{id}-body"
		onclick={() => (open = !open)}
	>
		<ChevronRight
			class={[
				'size-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none',
				open && 'rotate-90'
			]}
			aria-hidden="true"
		/>
		<span class="flex min-w-0 flex-1 flex-col">
			<span class="text-sm font-medium">{count}</span>
			<span class="text-xs text-muted-foreground">{hint}</span>
		</span>
	</button>
	{#if open}
		<div id="{id}-body" class="flex flex-col pl-6">
			{@render children()}
		</div>
	{/if}
</div>
