<script lang="ts">
	import Construction from '@lucide/svelte/icons/construction';
	import { m } from '#lib/paraglide/messages.js';
	import PageHeader from './page/PageHeader.svelte';
	import * as Card from '#lib/components/ui/card/index.ts';

	// An area that the next milestone fills.
	let { title }: { title: string } = $props();
</script>

<svelte:head><title>{title} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader {title} />
	<Card.Root
		size="flush"
		class="flex flex-col items-center gap-3 border-dashed px-6 py-16 text-center text-muted-foreground"
	>
		<Construction class="size-8" aria-hidden="true" />
		<p>{m.placeholder_text()}</p>
	</Card.Root>
</div>
