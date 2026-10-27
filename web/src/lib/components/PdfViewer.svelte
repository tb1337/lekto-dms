<script lang="ts">
	// The legacy build runs in browsers without the newest JavaScript features.
	import type {
		PDFDocumentLoadingTask,
		PDFDocumentProxy,
		RenderTask
	} from 'pdfjs-dist/legacy/build/pdf.mjs';
	import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';
	import { onDestroy, onMount, type Snippet } from 'svelte';
	import { apiFetch } from '#lib/api/fetch.ts';
	import { apiError, ApiError } from '#lib/api/problem.ts';
	import { BASE } from '#lib/base.ts';
	import PageViewer from '#lib/components/PageViewer.svelte';
	import type { Mark, Place } from '#lib/document-view.ts';
	import { describeError } from '#lib/errors.ts';
	import { m } from '#lib/paraglide/messages.js';

	// Shows a PDF (PDF.js, worker and data files from this site) in the page viewer: its pages
	// side by side, zoomed by gesture. The file comes through the API client's fetch, so the
	// session and a lost sign-in are handled as elsewhere. A page is drawn when it comes near
	// the view, and anew at its size once a zoom has come to rest; until then it is scaled.
	let {
		sources,
		label,
		marks = [],
		end,
		onsource,
		onpage
	}: {
		sources: readonly string[];
		label: string;
		marks?: readonly Mark[];
		/** At the end of the toolbar (the switch of a pane). */
		end?: Snippet;
		onsource?: (source: string) => void;
		/** The page in the upper third of the view, and how many there are. */
		onpage?: (current: number, total: number) => void;
	} = $props();

	/** PDF.js on demand (about half a megabyte), so the page around the viewer does not wait for it. */
	async function library() {
		const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs');
		pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
		return pdfjs;
	}

	/** PDF points to CSS pixels: 100 % is a page's printed size. */
	const POINT = 96 / 72;
	/** The most pixels a page's canvas gets; beyond it a page is drawn coarser. */
	const MOST_PIXELS = 16_000_000;

	let viewer = $state<PageViewer | null>(null);
	let sizes = $state<{ width: number; height: number }[]>([]);
	let loading = $state(true);
	let problem = $state<string | null>(null);
	let doc: PDFDocumentProxy | null = null;
	let loadingTask: PDFDocumentLoadingTask | null = null;
	let destroyed = false;
	// Plain bookkeeping, nothing in the markup reads these.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const tasks = new Map<number, RenderTask>();
	// The width in CSS pixels and the device pixel ratio each page was last drawn for.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const drawn = new Map<number, string>();

	async function open() {
		loading = true;
		problem = null;
		// PDF.js loads while the file is on its way.
		const loaded = library();
		// Reported where it is awaited; when the file fails first, it is no unhandled rejection.
		loaded.catch(() => {});
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
			const pdfjs = await loaded;
			// The viewer may have closed while the file was on its way: then no document is opened
			// (it would never be destroyed), and one that finished opening meanwhile is dropped.
			if (destroyed) return;
			loadingTask = pdfjs.getDocument({
				data,
				wasmUrl: `${BASE}/pdfjs/wasm/`,
				standardFontDataUrl: `${BASE}/pdfjs/standard_fonts/`,
				cMapUrl: `${BASE}/pdfjs/cmaps/`,
				cMapPacked: true
			});
			doc = await loadingTask.promise;
			if (destroyed) {
				void loadingTask.destroy();
				return;
			}
			await measure();
		} catch (error) {
			problem =
				error instanceof Error && !(error instanceof ApiError)
					? error.message
					: describeError(error);
		} finally {
			loading = false;
		}
	}

	/** The size of every page at 100 %. */
	async function measure() {
		if (!doc) return;
		const next: { width: number; height: number }[] = [];
		for (let number = 1; number <= doc.numPages; number++) {
			const page = await doc.getPage(number);
			if (destroyed) return;
			const viewport = page.getViewport({ scale: 1 });
			next.push({ width: viewport.width * POINT, height: viewport.height * POINT });
		}
		sizes = next;
	}

	/** Draw a page for the width it stands at now; aside, then copied over at once, so a page
	 * never stands blank while it sharpens. */
	async function draw(number: number, node: HTMLElement) {
		const canvas = node.querySelector('canvas');
		const width = Math.round(node.clientWidth);
		const ratio = window.devicePixelRatio || 1;
		// The same CSS width on a screen of another density (the window moved) is drawn anew.
		const target = `${width}@${ratio}`;
		if (!doc || destroyed || !canvas || width === 0 || drawn.get(number) === target) return;
		drawn.set(number, target);
		tasks.get(number)?.cancel();
		const page = await doc.getPage(number);
		if (destroyed) return;
		const unscaled = page.getViewport({ scale: 1 });
		let scale = (width / unscaled.width) * ratio;
		const pixels = unscaled.width * unscaled.height * scale * scale;
		if (pixels > MOST_PIXELS) scale *= Math.sqrt(MOST_PIXELS / pixels);
		const viewport = page.getViewport({ scale });
		const sheet = window.document.createElement('canvas');
		sheet.width = Math.floor(viewport.width);
		sheet.height = Math.floor(viewport.height);
		const task = page.render({ canvas: sheet, viewport });
		tasks.set(number, task);
		try {
			await task.promise;
		} catch {
			// Cancelled by a newer drawing of the page, or the viewer is gone.
			if (drawn.get(number) === target) drawn.delete(number);
			return;
		}
		if (tasks.get(number) === task) tasks.delete(number);
		canvas.width = sheet.width;
		canvas.height = sheet.height;
		canvas.getContext('2d')?.drawImage(sheet, 0, 0);
	}

	/** Scroll so that the place stands in the upper third of the view. */
	export function reveal(place: Place) {
		viewer?.reveal(place);
	}

	onMount(() => {
		void open();
	});
	onDestroy(() => {
		destroyed = true;
		for (const task of tasks.values()) task.cancel();
		void loadingTask?.destroy();
	});
</script>

<PageViewer
	bind:this={viewer}
	{sizes}
	{label}
	{marks}
	{loading}
	{problem}
	{end}
	{onpage}
	onshow={(number, node) => void draw(number, node)}
	onsettle={(pages) => {
		for (const { number, node } of pages) void draw(number, node);
	}}
>
	{#snippet page()}
		<canvas class="size-full" aria-hidden="true"></canvas>
	{/snippet}
</PageViewer>
