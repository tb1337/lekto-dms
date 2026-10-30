<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { goto } from '$app/navigation';

	// The way back to the list a page came from; with `state`, the history entry it had (the
	// words of a search, which never stand in the address).
	let { href, label, state }: { href: string; label: string; state?: App.PageState } = $props();

	function back(event: MouseEvent) {
		if (!state || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
		event.preventDefault();
		void goto(href, { state, persistState: true });
	}
</script>

<a
	{href}
	onclick={back}
	class="relative inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground after:absolute after:-inset-x-1 after:-inset-y-3 hover:text-foreground"
>
	<ArrowLeft class="size-4" aria-hidden="true" />
	{label}
</a>
