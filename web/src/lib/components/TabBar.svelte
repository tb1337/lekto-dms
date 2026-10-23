<script lang="ts" module>
	export interface Tab {
		/** Compared with `current`. */
		key: string;
		href: string;
		label: string;
		/** A number after the name (the documents in the tab); none when 0. */
		count?: number;
		/** A dot after the name, read out as this (something to look at there). */
		marker?: string;
	}
</script>

<script lang="ts">
	import { slidingPill } from '#lib/sliding-pill.ts';
	import { cn } from '#lib/utils.ts';

	// The tabs of a page (inbox, document, master data): links in a pill, the current one on a
	// light pill that moves over when another is chosen (`sliding-pill.ts`; Tobi, 20.10.2026).
	// Where they are wider than the room (a phone) they scroll sideways in their own row, the
	// current one in view, again when counts widen them; with `fill` they share a phone's width
	// equally instead.
	let {
		label,
		tabs,
		current,
		fill = false
	}: { label: string; tabs: readonly Tab[]; current: string; fill?: boolean } = $props();

	let bar = $state<HTMLElement | null>(null);

	$effect(() => {
		void current;
		void tabs;
		const chosen = bar?.querySelector<HTMLElement>('[aria-current="page"]');
		if (!bar || !chosen) return;
		const left = chosen.offsetLeft - (bar.clientWidth - chosen.offsetWidth) / 2;
		bar.scrollLeft = Math.max(0, left);
	});
</script>

<nav
	bind:this={bar}
	{@attach slidingPill}
	aria-label={label}
	class={cn(
		'relative flex w-fit max-w-full gap-1 overflow-x-auto rounded-full bg-secondary p-1',
		fill && 'max-sm:grid max-sm:w-full max-sm:auto-cols-fr max-sm:grid-flow-col'
	)}
>
	<span
		data-pill
		hidden
		aria-hidden="true"
		class="pointer-events-none absolute top-0 left-0 rounded-full bg-card shadow-sm data-moving:motion-safe:transition-[transform,width,height] data-moving:motion-safe:duration-300 data-moving:motion-safe:ease-out"
	></span>
	{#each tabs as tab (tab.key)}
		<a
			href={tab.href}
			aria-current={tab.key === current ? 'page' : undefined}
			class={cn(
				'relative inline-flex h-11 shrink-0 items-center justify-center gap-1.5 rounded-full px-3.5 text-sm whitespace-nowrap transition-colors sm:h-[34px] sm:px-4',
				fill && 'max-sm:px-1',
				tab.key === current
					? 'font-medium text-foreground'
					: 'text-muted-foreground hover:text-foreground'
			)}
		>
			{tab.label}
			{#if tab.count}
				<span class="text-xs font-normal text-muted-foreground tabular-nums">{tab.count}</span>
			{/if}
			{#if tab.marker}
				<span
					class="size-[7px] rounded-full bg-lane-yellow-mark ring-1 ring-lane-yellow-mark-edge ring-inset"
					aria-hidden="true"
				></span>
				<span class="sr-only">{tab.marker}</span>
			{/if}
		</a>
	{/each}
</nav>
