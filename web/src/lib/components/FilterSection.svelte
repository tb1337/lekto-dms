<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import type { Snippet } from 'svelte';

	// A group of the filters that opens and closes; closed or open it says what is chosen in
	// it (`summary`).
	let {
		title,
		summary = null,
		open = $bindable(true),
		children
	}: { title: string; summary?: string | null; open?: boolean; children: Snippet } = $props();

	const id = $props.id();
</script>

<section class="rounded-2xl border bg-card px-3" aria-labelledby="{id}-title">
	<h3 class="m-0">
		<button
			type="button"
			id="{id}-title"
			class="flex h-10 w-full items-center gap-2 text-left"
			aria-expanded={open}
			aria-controls="{id}-body"
			onclick={() => (open = !open)}
		>
			<span
				class="min-w-0 flex-1 truncate text-xs font-semibold tracking-wider text-muted-foreground uppercase"
			>
				{title}
			</span>
			{#if summary}
				<span class="max-w-[50%] truncate text-xs font-semibold text-brand">{summary}</span>
			{/if}
			<ChevronDown
				class={['size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180']}
				aria-hidden="true"
			/>
		</button>
	</h3>
	{#if open}
		<div id="{id}-body" class="flex flex-col gap-3 pb-3">
			{@render children()}
		</div>
	{/if}
</section>
