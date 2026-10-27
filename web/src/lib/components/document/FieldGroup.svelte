<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn } from '#lib/utils.ts';
	import { cardVariants } from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';

	// A group of fields on a card of its own: basics, global fields, fields of the type; the
	// filing box uses the same card. `action` stands at the end of the head (a button).
	let {
		id,
		icon: Icon,
		title,
		hint,
		action,
		class: className,
		children,
		...rest
	}: {
		id: string;
		icon: Component;
		title: string;
		hint: string;
		action?: Snippet;
		class?: string;
		children: Snippet;
	} & Omit<HTMLAttributes<HTMLElement>, 'id' | 'title' | 'class' | 'children'> = $props();
</script>

<section
	aria-labelledby={id}
	class={cn(cardVariants({ size: 'flush' }), 'flex flex-col gap-1.5 px-4 pt-3.5 pb-3', className)}
	{...rest}
>
	<div class="mb-0.5 flex items-center gap-2.5 border-b border-muted pb-2.5">
		<span
			class="grid size-[30px] shrink-0 place-items-center rounded-lg bg-panel text-brand"
			aria-hidden="true"
		>
			<Icon class="size-4" />
		</span>
		<div class="flex min-w-0 flex-col">
			<SectionTitle size="card" level={3} {id}>{title}</SectionTitle>
			<span class="text-xs text-muted-foreground">{hint}</span>
		</div>
		{#if action}{@render action()}{/if}
	</div>
	{@render children()}
</section>
