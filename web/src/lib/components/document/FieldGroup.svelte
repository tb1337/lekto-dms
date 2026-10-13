<script lang="ts">
	import type { Component, Snippet } from 'svelte';

	// A group of fields on a card of its own: basics, global fields, fields of the type.
	let {
		id,
		icon: Icon,
		title,
		hint,
		children
	}: { id: string; icon: Component; title: string; hint: string; children: Snippet } = $props();
</script>

<section
	aria-labelledby={id}
	class="flex flex-col gap-1.5 rounded-2xl border bg-card px-4 pt-3.5 pb-3"
>
	<div class="mb-0.5 flex items-center gap-2.5 border-b border-muted pb-2.5">
		<span
			class="grid size-[30px] shrink-0 place-items-center rounded-lg bg-panel text-brand"
			aria-hidden="true"
		>
			<Icon class="size-4" />
		</span>
		<div class="flex min-w-0 flex-col">
			<h3 {id} class="text-[0.95rem] leading-tight font-semibold">{title}</h3>
			<span class="text-xs text-muted-foreground">{hint}</span>
		</div>
	</div>
	{@render children()}
</section>
