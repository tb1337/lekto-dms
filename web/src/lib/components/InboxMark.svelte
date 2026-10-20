<script lang="ts">
	import Inbox from '@lucide/svelte/icons/inbox';
	import type { components } from '#lib/api/schema.ts';
	import { inboxTabHref, openTabOf } from '#lib/inbox-view.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// "In the inbox" at a document of the archive that stands open there: a link to the tab it
	// stands under. On a phone only its icon shows. As a `badge` (on a card's corner, Tobi,
	// 20.10.2026) only its icon always, filled, the words as tooltip; a ring in the page's colour
	// cuts it free of the card. Its area reaches about 44 pixels for a finger.
	let {
		lane,
		badge = false,
		class: className = ''
	}: { lane: components['schemas']['Lane'] | null; badge?: boolean; class?: string } = $props();
</script>

<a
	href={inboxTabHref(openTabOf(lane))}
	title={badge ? m.in_inbox() : undefined}
	class={cn(
		'relative inline-flex shrink-0 items-center gap-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors after:absolute after:-inset-2',
		badge
			? 'size-[26px] justify-center bg-primary text-primary-foreground shadow-[0_0_0_2px_var(--background),0_1px_4px_rgb(0_0_0/0.25)] hover:bg-primary/90'
			: 'h-7 border bg-card px-2 text-primary hover:border-primary sm:px-2.5',
		className
	)}
>
	<Inbox class="size-3.5 shrink-0" aria-hidden="true" />
	<span class={badge ? 'sr-only' : 'max-sm:sr-only'}>{m.in_inbox()}</span>
</a>
