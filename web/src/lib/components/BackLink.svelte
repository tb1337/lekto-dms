<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';

	// The way back to the list a page came from.
	let { href, label }: { href: string; label: string } = $props();
</script>

<a
	{href}
	class="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
>
	<ArrowLeft class="size-4" aria-hidden="true" />
	{label}
</a>
