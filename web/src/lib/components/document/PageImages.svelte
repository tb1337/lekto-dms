<script lang="ts">
	import type { Snippet } from 'svelte';
	import PageViewer from '#lib/components/PageViewer.svelte';
	import { m } from '#lib/paraglide/messages.js';

	// The page images (WebP from the original), shown until the archive PDF exists: they come
	// early, while the text is still being recognised; no marks, those belong to the archive.
	// The same viewer as the PDF's: side by side, zoomed by gesture.
	let {
		documentId,
		pageCount,
		label,
		end,
		onpage
	}: {
		documentId: string;
		pageCount: number;
		label: string;
		/** At the end of the toolbar (the switch of a pane). */
		end?: Snippet;
		/** The page in the upper third of the view, and how many there are. */
		onpage?: (current: number, total: number) => void;
	} = $props();

	/** An image is as wide as its page: 100 % is A4's width; its height once it is loaded. */
	const WIDTH = 793;
	let aspects = $state<Record<number, number>>({});
	const sizes = $derived(
		Array.from({ length: pageCount }, (_, index) => ({
			width: WIDTH,
			height: WIDTH * (aspects[index + 1] ?? Math.SQRT2)
		}))
	);
</script>

<PageViewer {sizes} {label} note={m.pages_preview()} {end} {onpage}>
	{#snippet page(number: number)}
		<img
			src="/api/v1/documents/{documentId}/pages/{number}"
			alt={m.page_image({ number })}
			loading="lazy"
			decoding="async"
			class="size-full object-contain"
			onload={(event) => {
				const image = event.currentTarget as HTMLImageElement;
				if (image.naturalWidth > 0) aspects[number] = image.naturalHeight / image.naturalWidth;
			}}
		/>
	{/snippet}
</PageViewer>
