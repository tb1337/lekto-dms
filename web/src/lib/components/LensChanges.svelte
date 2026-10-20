<script lang="ts">
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The page shows other filters, words or another sort than the open lens: keep them in it,
	// make a new lens of them, or go back to the lens.
	let {
		name,
		busy = false,
		onsave,
		onsaveas,
		ondiscard
	}: {
		name: string;
		busy?: boolean;
		onsave: () => void;
		onsaveas: () => void;
		ondiscard: () => void;
	} = $props();
</script>

<div
	role="status"
	class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-lane-yellow-foreground/40 bg-lane-yellow px-4 py-2.5"
>
	<CircleAlert class="size-4 shrink-0 text-lane-yellow-foreground" aria-hidden="true" />
	<span class="min-w-0 flex-1 text-sm">{m.lens_changed()}</span>
	<div class="flex flex-wrap gap-2">
		<Button variant="ghost" size="sm" class="rounded-full" disabled={busy} onclick={ondiscard}>
			{m.lens_discard()}
		</Button>
		<Button variant="outline" size="sm" class="rounded-full" disabled={busy} onclick={onsaveas}>
			{m.lens_save_as()}
		</Button>
		<Button size="sm" class="rounded-full" disabled={busy} onclick={onsave}>
			{m.lens_save_into({ name })}
		</Button>
	</div>
</div>
