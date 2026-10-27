<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import type { Component, Snippet } from 'svelte';
	import * as Card from '#lib/components/ui/card/index.ts';

	// A tile of the overview (Tobi, 27.10.2026): what a place holds that waits for someone, under
	// its name and icon, and the way there at the foot.
	let {
		title,
		icon: Icon,
		href,
		go,
		children
	}: {
		title: string;
		icon: Component;
		href: string;
		/** The way there, a verb phrase ("Zum Posteingang"). */
		go: string;
		children: Snippet;
	} = $props();
</script>

<Card.Root as="section" class="flex flex-col gap-3" aria-label={title}>
	<div class="flex items-center gap-2 text-muted-foreground">
		<Icon class="size-4 shrink-0" aria-hidden="true" />
		<Card.Title class="text-foreground">{title}</Card.Title>
	</div>
	{@render children()}
	<a
		{href}
		class="mt-auto inline-flex min-h-8 items-center gap-1.5 self-start font-medium text-brand hover:underline"
	>
		{go}
		<ArrowRight class="size-4" aria-hidden="true" />
	</a>
</Card.Root>
