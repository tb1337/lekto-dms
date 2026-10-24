<script lang="ts">
	import { pageImageHref } from '#lib/document-view.ts';
	import type { CodeFacts } from '#lib/facts.ts';

	// A code as it stands on its (first) page: a square cut from the page image around its
	// box, with some room. The page images come from the original, the box from the archive; for a
	// turned or deskewed scan the cut is a little off, so it keeps room around the code.
	let {
		documentId,
		code,
		size = 64
	}: { documentId: string; code: CodeFacts; size?: number } = $props();

	// Height of the page by its width; known once the image is loaded.
	let aspect = $state<number | null>(null);

	const place = $derived(code.places[0]);

	const crop = $derived.by(() => {
		const ratio = aspect ?? Math.SQRT2;
		const { x, y, width, height } = place.boxes[0];
		const side = Math.max(width, height * ratio) * 1.5;
		const left = x + width / 2 - side / 2;
		const top = (y + height / 2) * ratio - side / 2;
		const scale = size / side; // pixels per page width
		return `width: ${scale}px; left: ${-left * scale}px; top: ${-top * scale}px`;
	});
</script>

<div
	class="relative shrink-0 overflow-hidden rounded-lg border bg-white"
	style="width: {size}px; height: {size}px"
	aria-hidden="true"
>
	<img
		src={pageImageHref(documentId, place.page)}
		alt=""
		class="absolute max-w-none"
		style={crop}
		onload={(event) => {
			const image = event.currentTarget as HTMLImageElement;
			if (image.naturalWidth > 0) aspect = image.naturalHeight / image.naturalWidth;
		}}
	/>
</div>
