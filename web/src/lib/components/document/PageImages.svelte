<script lang="ts">
	import type { Snippet } from 'svelte';
	import PageViewer from '#lib/components/PageViewer.svelte';
	import { pageImageHref, type Mark, type Place } from '#lib/document-view.ts';
	import { m } from '#lib/paraglide/messages.js';
	import type { Layout } from '#lib/viewer/zoom.ts';

	// The page images (WebP from the original): in the document view until the archive PDF
	// exists (they come early, while the text is still being recognised), and in the Beam, with
	// the places it marks (`marks`, `reveal`). The same viewer as the PDF's: side by side, zoomed
	// by gesture.
	let {
		documentId,
		pageCount,
		label,
		marks = [],
		note = m.pages_preview(),
		start = null,
		end,
		onpage
	}: {
		documentId: string;
		pageCount: number;
		label: string;
		marks?: readonly Mark[];
		/** Said in the toolbar beside the page count. */
		note?: string | null;
		/** How the viewer starts (`PageViewer`). */
		start?: Layout | null;
		/** At the end of the toolbar (the switch of a pane). */
		end?: Snippet;
		/** The page in the upper third of the view, and how many there are. */
		onpage?: (current: number, total: number) => void;
	} = $props();

	let viewer = $state<PageViewer | null>(null);

	/** Scroll so that `place` stands in the upper third of the view. */
	export function reveal(place: Place) {
		viewer?.reveal(place);
	}

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

<PageViewer bind:this={viewer} {sizes} {label} {marks} {note} {start} {end} {onpage}>
	{#snippet page(number: number)}
		<img
			src={pageImageHref(documentId, number)}
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
