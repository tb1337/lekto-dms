<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';

	// The way back to the list a page came from.
	let { href, label }: { href: string; label: string } = $props();
</script>

<a
	{href}
	class="relative inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground after:absolute after:-inset-x-1 after:-inset-y-3 hover:text-foreground"
>
	<ArrowLeft class="size-4" aria-hidden="true" />
	{label}
</a>
