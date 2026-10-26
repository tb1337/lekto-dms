<script lang="ts">
	import Inbox from '@lucide/svelte/icons/inbox';
	import { inboxDocument } from '#lib/document-view.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';
	import * as Tooltip from '#lib/components/ui/tooltip/index.ts';

	// "In the inbox" at a document of the archive that stands open there: a link to the document
	// as opened from the inbox (Tobi, 20.10.2026: to the document, not to the inbox), with its
	// neighbours there and the next one to decide. On a phone only its icon shows. As a `badge`
	// (in a card's head) only its icon, in the accent's tone, the words as tooltip. Its area
	// reaches about 44 pixels for a finger.
	let {
		id,
		badge = false,
		class: className = ''
	}: { id: string; badge?: boolean; class?: string } = $props();
</script>

{#snippet mark(props: Record<string, unknown>)}
	<a
		{...props}
		href={inboxDocument(id)}
		class={cn(
			'relative inline-flex shrink-0 items-center gap-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors after:absolute after:-inset-2.5',
			badge
				? 'size-6 justify-center border border-primary/30 bg-primary/10 text-brand hover:bg-primary/20'
				: 'h-7 border bg-card px-2 text-brand hover:border-primary sm:px-2.5',
			className
		)}
	>
		<Inbox class="size-3.5 shrink-0" aria-hidden="true" />
		<span class={badge ? 'sr-only' : 'max-sm:sr-only'}>{m.in_inbox()}</span>
	</a>
{/snippet}

{#if badge}
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}{@render mark(props)}{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Content>{m.in_inbox()}</Tooltip.Content>
	</Tooltip.Root>
{:else}
	{@render mark({})}
{/if}
