<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// "Beta" at an area that is new and may be wrong (Tobi, 26.10.2026): small and raised at its
	// menu entry, and with `tip` larger beside the page's title, where it is the button of an info
	// tip (`InfoTip`) that says what the beta means. Pale violet with dark writing (`--beta`), as
	// the chips are drawn: not the petrol, not a lane.
	let { tip, class: className = '' }: { tip?: string; class?: string } = $props();

	const PILL =
		'inline-flex items-center rounded-full bg-beta font-bold tracking-[0.06em] text-beta-foreground uppercase';
</script>

{#if tip}
	<InfoTip
		label={m.beta_about()}
		class="w-80"
		buttonClass={cn(
			PILL,
			'relative h-6 gap-1.5 border border-beta-foreground/15 px-2.5 text-xs after:absolute after:inset-x-0 after:-inset-y-2.5 hover:bg-beta-foreground/12 data-open:bg-beta-foreground/12',
			className
		)}
	>
		{#snippet trigger()}
			<Info class="size-[13px] [&]:stroke-[2.4]" aria-hidden="true" />
			{m.beta()}
		{/snippet}
		<p>{tip}</p>
	</InfoTip>
{:else}
	<span class={cn(PILL, 'h-3.5 -translate-y-[7px] px-[5px] text-nano leading-none', className)}
		>{m.beta()}</span
	>
{/if}
