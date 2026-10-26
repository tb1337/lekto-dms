<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import { Popover } from 'bits-ui';
	import type { Snippet } from 'svelte';
	import { cn } from '#lib/utils.ts';

	// An info button and what it explains in a dark box beside it, for every info icon of the UI
	// (field help, token figures, where a value comes from). The box lies in a layer over the page
	// and keeps inside the window, turning to the side with room: never cut off by a column or the
	// window (Tobi, 20.10.2026). It opens while the mouse is over the button or the box (so links in
	// it can be followed) and on a click, a tap or Enter; Escape or a click elsewhere closes it.
	// Opened by hand, the focus goes into the box; on hover it stays where it is. The button is
	// the info icon, or with `trigger` what stands there (the "Beta" pill), styled by `buttonClass`.
	let {
		label,
		id,
		size = 'md',
		class: className = '',
		trigger,
		buttonClass = '',
		children
	}: {
		/** The button's name ("About groups"). */
		label: string;
		id?: string;
		size?: 'sm' | 'md';
		/** The width of the box. */
		class?: string;
		/** The button's content instead of the info icon. */
		trigger?: Snippet;
		/** The button's look with `trigger`; `data-open` marks it while the box is open. */
		buttonClass?: string;
		children: Snippet;
	} = $props();

	let open = $state(false);
	// Opened by a click or a key, not by the mouse passing.
	let byHand = $state(false);
	let button = $state<HTMLButtonElement | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;

	function enter(event: PointerEvent) {
		if (event.pointerType !== 'mouse') return;
		clearTimeout(timer);
		if (!open) {
			byHand = false;
			open = true;
		}
	}

	function leave(event: PointerEvent) {
		if (event.pointerType !== 'mouse' || byHand) return;
		clearTimeout(timer);
		// Time to cross the gap between the button and the box.
		timer = setTimeout(() => (open = false), 150);
	}

	function click() {
		clearTimeout(timer);
		if (open && byHand) {
			open = false;
			return;
		}
		byHand = true;
		open = true;
	}
</script>

<button
	bind:this={button}
	type="button"
	aria-label={label}
	aria-expanded={open}
	aria-controls={open ? id : undefined}
	onpointerenter={enter}
	onpointerleave={leave}
	onclick={click}
	data-open={open || undefined}
	class={cn(
		'shrink-0 rounded-full transition-colors',
		trigger
			? buttonClass
			: cn(
					'grid place-items-center text-muted-foreground hover:text-foreground',
					size === 'sm' ? 'size-6' : 'size-7',
					open && 'bg-secondary text-foreground'
				)
	)}
>
	{#if trigger}
		{@render trigger()}
	{:else}
		<Info class={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden="true" />
	{/if}
</button>
<Popover.Root bind:open onOpenChange={(next) => next || (byHand = false)}>
	<Popover.Portal>
		<Popover.Content
			{id}
			data-info-tip
			customAnchor={button}
			side="bottom"
			sideOffset={6}
			collisionPadding={8}
			trapFocus={byHand}
			onOpenAutoFocus={(event) => byHand || event.preventDefault()}
			onCloseAutoFocus={(event) => byHand || event.preventDefault()}
			onInteractOutside={(event) => {
				// The button toggles itself.
				if (button?.contains(event.target as Node)) event.preventDefault();
			}}
			onpointerenter={enter}
			onpointerleave={leave}
			class={cn(
				'z-50 max-w-[calc(100vw-1rem)] rounded-xl bg-foreground px-3.5 py-3 text-[12.5px] leading-normal text-background shadow-lg outline-none',
				className
			)}
		>
			{@render children()}
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
