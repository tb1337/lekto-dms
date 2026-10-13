<script lang="ts">
	import Minus from '@lucide/svelte/icons/minus';
	import MoveHorizontal from '@lucide/svelte/icons/move-horizontal';
	import Plus from '@lucide/svelte/icons/plus';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The page images (WebP from the original), shown until the archive PDF exists: they come
	// early, while the text is still being recognised; no marks, those belong to the archive.
	let { documentId, pageCount, label }: { documentId: string; pageCount: number; label: string } =
		$props();

	const MIN_ZOOM = 0.5;
	const MAX_ZOOM = 2;
	let zoom = $state(1);
	const numbers = $derived(Array.from({ length: pageCount }, (_, index) => index + 1));

	function setZoom(value: number) {
		zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
	}
</script>

<div class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-surface">
	<div class="flex items-center gap-1 border-b bg-card px-3 py-2">
		<Button
			variant="ghost"
			size="icon"
			onclick={() => setZoom(zoom / 1.25)}
			aria-label={m.pdf_zoom_out()}
		>
			<Minus aria-hidden="true" />
		</Button>
		<span class="min-w-12 text-center text-sm tabular-nums" aria-live="polite">
			{formatNumber(zoom, { style: 'percent', maximumFractionDigits: 0 })}
		</span>
		<Button
			variant="ghost"
			size="icon"
			onclick={() => setZoom(zoom * 1.25)}
			aria-label={m.pdf_zoom_in()}
		>
			<Plus aria-hidden="true" />
		</Button>
		<Button variant="ghost" size="icon" onclick={() => setZoom(1)} aria-label={m.pdf_fit_width()}>
			<MoveHorizontal aria-hidden="true" />
		</Button>
		<span class="ml-auto text-sm text-muted-foreground">{m.pages_preview()}</span>
	</div>
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		role="document"
		tabindex="0"
		aria-label={label}
		class="flex min-h-[24rem] flex-1 flex-col items-center gap-3 overflow-auto p-3"
	>
		{#each numbers as number (number)}
			<img
				src="/api/v1/documents/{documentId}/pages/{number}"
				alt={m.page_image({ number })}
				loading="lazy"
				class="max-w-none shrink-0 bg-white shadow-sm"
				style:width={`${zoom * 100}%`}
			/>
		{/each}
	</div>
</div>
