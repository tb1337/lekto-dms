<script lang="ts">
	import Minus from '@lucide/svelte/icons/minus';
	import MoveHorizontal from '@lucide/svelte/icons/move-horizontal';
	import Plus from '@lucide/svelte/icons/plus';
	// The legacy build runs in browsers without the newest JavaScript features.
	import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs';
	import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';
	import { onDestroy, onMount } from 'svelte';
	import { apiFetch } from '#lib/api/fetch.ts';
	import { apiError, ApiError } from '#lib/api/problem.ts';
	import { BASE } from '#lib/base.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import type { Mark, Place } from '#lib/document-view.ts';
	import { describeError } from '#lib/errors.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// Shows a PDF page by page (PDF.js, worker and data files from this site). The file comes
	// through the API client's fetch, so the session and a lost sign-in are handled as elsewhere.
	// `marks` are drawn over the pages (boxes are fractions of a page), `reveal` scrolls to one.
	let {
		sources,
		label,
		marks = [],
		onsource
	}: {
		sources: readonly string[];
		label: string;
		marks?: readonly Mark[];
		onsource?: (source: string) => void;
	} = $props();

	pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

	let container = $state<HTMLDivElement | null>(null);
	let pages = $state<{ width: number; height: number }[]>([]);
	let loading = $state(true);
	let problem = $state<string | null>(null);
	let zoom = $state(1);
	let current = $state(1);
	let doc: pdfjs.PDFDocumentProxy | null = null;
	let loadingTask: pdfjs.PDFDocumentLoadingTask | null = null;
	let observer: IntersectionObserver | null = null;
	// Only the newest layout may set the pages; none after the viewer is gone.
	let layoutRun = 0;
	let destroyed = false;
	// Plain bookkeeping, nothing in the markup reads these.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const tasks = new Map<number, pdfjs.RenderTask>();
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const rendered = new Set<number>();

	const MIN_ZOOM = 0.5;
	const MAX_ZOOM = 3;

	function fitWidth(): number {
		return Math.max(200, (container?.clientWidth ?? 800) - 24);
	}

	async function open() {
		loading = true;
		problem = null;
		try {
			// The first source that exists: the archive PDF, else the original.
			let response: Response | null = null;
			for (const src of sources) {
				const answer = await apiFetch(new Request(new URL(src, location.origin)));
				if (answer.ok) {
					response = answer;
					onsource?.(src);
					break;
				}
				if (answer.status !== 404) throw await apiError(answer);
			}
			if (!response) throw new Error(m.pdf_missing());
			const data = new Uint8Array(await response.arrayBuffer());
			loadingTask = pdfjs.getDocument({
				data,
				wasmUrl: `${BASE}/pdfjs/wasm/`,
				standardFontDataUrl: `${BASE}/pdfjs/standard_fonts/`,
				cMapUrl: `${BASE}/pdfjs/cmaps/`,
				cMapPacked: true
			});
			doc = await loadingTask.promise;
			await layout();
		} catch (error) {
			problem =
				error instanceof Error && !(error instanceof ApiError)
					? error.message
					: describeError(error);
		} finally {
			loading = false;
		}
	}

	/** Sizes of all pages at the current zoom; the canvases fill in when they come into view. */
	async function layout() {
		if (!doc) return;
		const run = ++layoutRun;
		const next: { width: number; height: number }[] = [];
		const base = fitWidth();
		for (let number = 1; number <= doc.numPages; number++) {
			const page = await doc.getPage(number);
			if (destroyed || run !== layoutRun) return;
			const viewport = page.getViewport({ scale: 1 });
			const scale = (base / viewport.width) * zoom;
			next.push({ width: viewport.width * scale, height: viewport.height * scale });
		}
		for (const task of tasks.values()) task.cancel();
		tasks.clear();
		rendered.clear();
		pages = next;
	}

	async function draw(number: number, canvas: HTMLCanvasElement) {
		if (!doc || destroyed || rendered.has(number)) return;
		rendered.add(number);
		const page = await doc.getPage(number);
		const size = pages[number - 1];
		if (destroyed || !size) {
			rendered.delete(number);
			return;
		}
		const unscaled = page.getViewport({ scale: 1 });
		const ratio = window.devicePixelRatio || 1;
		const viewport = page.getViewport({ scale: (size.width / unscaled.width) * ratio });
		canvas.width = Math.floor(viewport.width);
		canvas.height = Math.floor(viewport.height);
		const task = page.render({ canvas, viewport });
		tasks.set(number, task);
		try {
			await task.promise;
		} catch {
			rendered.delete(number); // cancelled by a new layout
		}
	}

	// One observer serves all pages: each entry names its page through the observed element.
	function visible(entries: IntersectionObserverEntry[]) {
		for (const entry of entries) {
			const target = entry.target as HTMLElement;
			const number = Number(target.dataset.page);
			const canvas = target.querySelector('canvas');
			if (entry.isIntersecting && canvas && number > 0) void draw(number, canvas);
		}
	}

	function watch(node: HTMLElement, number: number) {
		node.dataset.page = String(number);
		observer ??= new IntersectionObserver(visible, { root: container, rootMargin: '300px 0px' });
		const own = observer;
		own.observe(node);
		return { destroy: () => own.unobserve(node) };
	}

	async function setZoom(value: number) {
		zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
		observer?.disconnect();
		observer = null;
		await layout();
	}

	/** The page shown in the upper third of the view (the pages are drawn ahead of it). */
	function follow() {
		if (!container) return;
		const line = container.scrollTop + container.clientHeight / 3;
		let found = 1;
		for (const node of container.querySelectorAll<HTMLElement>('[data-page]')) {
			if (node.offsetTop > line) break;
			found = Number(node.dataset.page);
		}
		current = found;
	}

	/** Scroll so that the place stands in the upper third of the view. */
	export function reveal(place: Place) {
		const node = container?.querySelector<HTMLElement>(`[data-page="${place.page}"]`);
		if (!container || !node) return;
		const y = node.offsetTop + (place.boxes[0]?.y ?? 0) * node.offsetHeight;
		container.scrollTo({ top: Math.max(0, y - container.clientHeight / 3), behavior: 'smooth' });
	}

	function keydown(event: KeyboardEvent) {
		if (event.key === '+' || event.key === '=') void setZoom(zoom * 1.25);
		else if (event.key === '-') void setZoom(zoom / 1.25);
		else if (event.key === '0') void setZoom(1);
	}

	// The pages fit the width: a viewer that gets narrower or wider (window, panel) lays them
	// out anew.
	let width = 0;
	let resizeTimer: ReturnType<typeof setTimeout> | undefined;
	function resized() {
		const next = container?.clientWidth ?? 0;
		if (Math.abs(next - width) < 24) return;
		width = next;
		clearTimeout(resizeTimer);
		resizeTimer = setTimeout(() => {
			observer?.disconnect();
			observer = null;
			void layout();
		}, 150);
	}

	onMount(() => {
		void open();
		const watcher = new ResizeObserver(resized);
		if (container) {
			width = container.clientWidth;
			watcher.observe(container);
		}
		return () => {
			watcher.disconnect();
			clearTimeout(resizeTimer);
		};
	});
	onDestroy(() => {
		destroyed = true;
		observer?.disconnect();
		for (const task of tasks.values()) task.cancel();
		void loadingTask?.destroy();
	});
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
			{Math.round(zoom * 100)} %
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
		<span class="ml-auto text-sm text-muted-foreground">
			{m.pdf_page({ current, total: pages.length })}
		</span>
	</div>
	<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
	<div
		bind:this={container}
		role="document"
		tabindex="0"
		aria-label={label}
		onkeydown={keydown}
		onscroll={follow}
		class="relative flex min-h-[24rem] flex-1 flex-col items-center gap-3 overflow-auto p-3"
	>
		{#if loading}
			<p class="py-16 text-muted-foreground">{m.loading()}</p>
		{:else if problem}
			<p class="py-16 text-destructive" role="alert">{problem}</p>
		{:else}
			<!-- A new width (zoom, resize) makes new page elements, and `watch` observes them anew. -->
			{#each pages as size, index (`${index}-${size.width}`)}
				<div
					use:watch={index + 1}
					class="relative shrink-0 bg-white shadow-sm"
					style:width={`${size.width}px`}
					style:height={`${size.height}px`}
				>
					<canvas class="size-full" aria-hidden="true"></canvas>
					{#each marks.filter((mark) => mark.page === index + 1) as mark, markIndex (`${mark.key}-${markIndex}`)}
						{#each mark.boxes as box, boxIndex (boxIndex)}
							<div
								class={cn(
									'pointer-events-none absolute rounded-[3px] transition-shadow',
									mark.derived
										? 'bg-primary/10 outline-2 outline-offset-1 outline-primary outline-dashed'
										: 'bg-primary/20 ring-2 ring-primary',
									mark.pinned &&
										'shadow-[0_0_0_7px_color-mix(in_oklab,var(--primary)_22%,transparent)]'
								)}
								style:left={`${box.x * 100}%`}
								style:top={`${box.y * 100}%`}
								style:width={`${box.width * 100}%`}
								style:height={`${box.height * 100}%`}
								aria-hidden="true"
							>
								{#if boxIndex === 0}
									<span
										class="absolute bottom-full left-0 mb-1 rounded-md bg-primary px-1.5 text-[10px] leading-4 font-semibold whitespace-nowrap text-primary-foreground"
									>
										{mark.label}
									</span>
								{/if}
							</div>
						{/each}
					{/each}
				</div>
			{/each}
		{/if}
	</div>
</div>
