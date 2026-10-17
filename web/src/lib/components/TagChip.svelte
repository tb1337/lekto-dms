<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import type { Tag } from '#lib/masterdata.svelte.ts';
	import { pathLabel } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// A tag as a chip: its own name, the path as tooltip and, where `interactive`, on a tap (a
	// phone has no hover); a group outlined, a topic square (tags are round); `onremove` adds a
	// button that removes it.
	let {
		tag,
		group = false,
		topic = false,
		interactive = false,
		size = 'md',
		onremove,
		removeLabel = ''
	}: {
		tag: Pick<Tag, 'id' | 'name' | 'path'>;
		group?: boolean;
		topic?: boolean;
		interactive?: boolean;
		size?: 'sm' | 'md';
		onremove?: () => void;
		removeLabel?: string;
	} = $props();

	const path = $derived(pathLabel(tag));
	const nested = $derived(tag.path.length > 1);
</script>

<span
	class={cn(
		'inline-flex max-w-full min-w-0 items-center gap-1',
		topic ? 'rounded-md border border-primary/25 bg-primary/10' : 'rounded-full',
		!topic && (group ? 'border bg-background' : 'bg-secondary'),
		size === 'sm' ? 'h-6 px-2 text-xs' : 'h-8 pl-3 text-sm',
		size === 'md' && (onremove ? 'pr-1' : 'pr-3')
	)}
	title={path}
>
	{#if interactive && nested}
		<Popover.Root>
			<Popover.Trigger
				class={cn('min-w-0 truncate hover:underline', topic ? 'rounded-sm' : 'rounded-full')}
				aria-label={path}
			>
				{tag.name}
			</Popover.Trigger>
			<Popover.Content class="w-auto max-w-72 px-3 py-2 text-sm" side="top">
				{path}
			</Popover.Content>
		</Popover.Root>
	{:else}
		<span class="min-w-0 truncate">{tag.name}</span>
	{/if}
	{#if onremove}
		<button
			type="button"
			class="grid size-6 shrink-0 place-items-center rounded-full hover:bg-background"
			aria-label={removeLabel}
			onclick={onremove}
		>
			<X class="size-3.5" aria-hidden="true" />
		</button>
	{/if}
</span>
