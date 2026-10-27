<script lang="ts">
	import type { Snippet } from 'svelte';
	import BackLink from '../BackLink.svelte';
	import PageTitle from './PageTitle.svelte';

	// The head of a page (web/DESIGN.md, "Page frame"): the way back, the title with what stands
	// beside it (a count, a badge), the page's actions level with the title, a subtitle and what
	// belongs to the head below it. It renders as siblings in the page's column, so the page's gap
	// stands between the way back and the title.
	let {
		title,
		back,
		aside,
		actions,
		subtitle,
		below,
		subtitleClass
	}: {
		/** The `<h1>`; a snippet when it holds more than words. */
		title: string | Snippet;
		back?: { href: string; label: string };
		/** Beside the title: a count, a badge, a pill. */
		aside?: Snippet;
		/** Level with the title, at the end of its row; the primary action last. */
		actions?: Snippet;
		subtitle?: string | Snippet;
		/** Under the subtitle, still part of the head (lines of state, notes). */
		below?: Snippet;
		subtitleClass?: string;
	} = $props();
</script>

{#if back}
	<BackLink href={back.href} label={back.label} />
{/if}
<div class="flex flex-col gap-1">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
			<PageTitle>
				{#if typeof title === 'string'}{title}{:else}{@render title()}{/if}
			</PageTitle>
			{@render aside?.()}
		</div>
		{#if actions}
			<div class="flex flex-wrap items-center gap-2">{@render actions()}</div>
		{/if}
	</div>
	{#if subtitle}
		<p class={['text-sm text-muted-foreground', subtitleClass]}>
			{#if typeof subtitle === 'string'}{subtitle}{:else}{@render subtitle()}{/if}
		</p>
	{/if}
	{@render below?.()}
</div>
