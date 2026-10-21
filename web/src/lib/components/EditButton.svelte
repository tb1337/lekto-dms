<script lang="ts">
	import Pencil from '@lucide/svelte/icons/pencil';
	import { Button, buttonVariants } from '#lib/components/ui/button/index.ts';
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
	{#if href}
		<a
			{href}
			aria-label={label}
			title={label}
			class={buttonVariants({ variant: 'ghost', size: 'icon' })}
		>
			<Pencil aria-hidden="true" />
		</a>
	{:else}
		<Button variant="ghost" size="icon" aria-label={label} title={label} {onclick}>
			<Pencil aria-hidden="true" />
		</Button>
	{/if}
</div>
