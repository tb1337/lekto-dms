<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as Sheet from '#lib/components/ui/sheet/index.ts';

	// A choice from many on a phone (web/DESIGN.md, "Dialogs"): a sheet from the bottom, 85 % of
	// the screen high, built on `ui/sheet`. A grab handle, then a row fixed on top with its
	// `title` and the way out (`close`: an X, "Fertig"), then what it offers (`children`), which
	// scrolls on its own. Nothing takes the focus when it opens: the keyboard waits for a tap,
	// and a close button shows no tooltip. A choice closes it: the caller sets `open` false.
	let {
		open = $bindable(false),
		title,
		onOpenChange,
		close,
		children
	}: {
		open?: boolean;
		/** The sheet's heading: "Kontakt wählen". */
		title: string;
		/** Hears of the sheet closing by itself (Escape, a tap outside). */
		onOpenChange?: (open: boolean) => void;
		/** The button at the right of the title that closes the sheet. */
		close: Snippet;
		children: Snippet;
	} = $props();
</script>

<Sheet.Root bind:open {onOpenChange}>
	<Sheet.Content
		side="bottom"
		showCloseButton={false}
		onOpenAutoFocus={(event) => event.preventDefault()}
		class="h-[85dvh] max-h-[85dvh] gap-0 overflow-hidden rounded-t-2xl p-0"
	>
		<span class="mx-auto mt-2 h-1.5 w-10 shrink-0 rounded-full bg-border" aria-hidden="true"></span>
		<div class="flex shrink-0 items-center justify-between gap-2 py-2 pr-2 pl-4">
			<Sheet.Title class="text-base font-semibold">{title}</Sheet.Title>
			{@render close()}
		</div>
		{@render children()}
	</Sheet.Content>
</Sheet.Root>
