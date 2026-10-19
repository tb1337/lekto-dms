<script lang="ts">
	import Inbox from '@lucide/svelte/icons/inbox';
	import type { components } from '#lib/api/schema.ts';
	import { inboxTabHref, openTabOf } from '#lib/inbox-view.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// "In the inbox" at a document of the archive that stands open there: a link to the tab it
	// stands under. On a phone only its icon shows, and `compact` (on a card) only its icon
	// always, the words as tooltip; its area reaches 44 pixels for a finger.
	let {
		lane,
		compact = false,
		class: className = ''
	}: { lane: components['schemas']['Lane'] | null; compact?: boolean; class?: string } = $props();
</script>

<a
	href={inboxTabHref(openTabOf(lane))}
	title={compact ? m.in_inbox() : undefined}
	class={cn(
		'relative inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border bg-card text-xs font-medium whitespace-nowrap text-primary transition-colors after:absolute after:-inset-2 hover:border-primary',
		compact ? 'w-7 justify-center shadow-sm' : 'px-2 sm:px-2.5',
		className
	)}
>
	<Inbox class="size-3.5 shrink-0" aria-hidden="true" />
	<span class={compact ? 'sr-only' : 'max-sm:sr-only'}>{m.in_inbox()}</span>
</a>
