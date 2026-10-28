<script lang="ts">
	import type { Snippet } from 'svelte';

	// The words a search or a lookup found, marked in the text around them: the snippet of a
	// hit in the documents list, the value at a place of an open identifier.
	let { children }: { children: Snippet } = $props();
</script>

<mark class="rounded-sm bg-lane-yellow px-0.5 text-lane-yellow-foreground"
	>{@render children()}</mark
>
