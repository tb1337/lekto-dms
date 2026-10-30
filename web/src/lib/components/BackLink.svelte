<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { goto } from '$app/navigation';

	// The way back to the place a page came from. With `back`, that (the history after a jump,
	// `lib/way-back.ts`); with `state`, `href` with the history entry it had (the words of a
	// search, which never stand in the address); else `href`.
	let {
		href,
		label,
		state,
		back
	}: { href: string; label: string; state?: App.PageState; back?: () => void } = $props();

	function follow(event: MouseEvent) {
		if (!(state || back) || event.button !== 0 || event.metaKey || event.ctrlKey) return;
		if (event.shiftKey) return;
		event.preventDefault();
		if (back) back();
		else void goto(href, { state, persistState: true });
	}
</script>

<a
	{href}
	onclick={follow}
	class="relative inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground after:absolute after:-inset-x-1 after:-inset-y-3 hover:text-foreground"
>
	<ArrowLeft class="size-4" aria-hidden="true" />
	{label}
</a>
