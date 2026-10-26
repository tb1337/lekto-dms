<script lang="ts">
	import Columns2 from '@lucide/svelte/icons/columns-2';
	import File from '@lucide/svelte/icons/file';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import Minus from '@lucide/svelte/icons/minus';
	import Plus from '@lucide/svelte/icons/plus';
	import { onMount, tick, type Snippet } from 'svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import type { Mark, Place } from '#lib/document-view.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';
	import { zoomGestures } from '#lib/viewer/gestures.ts';
	import {
		anchorOn,
		bounded,
		fitZoom,
		LAYOUTS,
		layoutAt,
		rowAt,
		shiftFor,
		type Anchor,
		type Layout,
		type Point,
		type Room
	} from '#lib/viewer/zoom.ts';
	import { Separator } from '#lib/components/ui/separator/index.ts';
	import IconButton from '#lib/components/IconButton.svelte';

	// The pages of a document side by side, wrapping into rows: the zoom decides how many stand
	// in a row (`viewer/zoom.ts`). Ctrl or ⌘ with the wheel, a pinch, the buttons and the keys
	// + − 0 zoom around the pointer; a double click enlarges a page and goes back. `marks` are
	// drawn over the pages (boxes are fractions of a page), `reveal` scrolls to one. What a page
	// shows comes from `page`; `onshow` tells when a page comes near the view, `onsettle` when
	// the zoom has come to rest, with the pages in view (to be drawn anew at their size);
	// `onpage` the page in the upper third of the view, as the toolbar counts it.
	let {
		sizes,
		label,
		marks = [],
		loading = false,
		problem = null,
		note = null,
		page,
		end,
		onshow,
		onsettle,
		onpage
	}: {
		/** Each page's size at 100 %, in CSS pixels. */
		sizes: readonly { width: number; height: number }[];
		label: string;
		marks?: readonly Mark[];
		loading?: boolean;
		problem?: string | null;
		/** Said in the toolbar beside the page count. */
		note?: string | null;
		page: Snippet<[number]>;
		/** At the end of the toolbar (the switch of a pane). */
		end?: Snippet;
		onshow?: (number: number, node: HTMLElement) => void;
		onsettle?: (pages: { number: number; node: HTMLElement }[]) => void;
		onpage?: (current: number, total: number) => void;
	} = $props();

	const NAMES: Record<Layout, { label: () => string; hint: () => string; icon: typeof File }> = {
		one: { label: m.pdf_layout_one, hint: m.pdf_layout_one_hint, icon: File },
		two: { label: m.pdf_layout_two, hint: m.pdf_layout_two_hint, icon: Columns2 },
		overview: { label: m.pdf_layout_overview, hint: m.pdf_layout_overview_hint, icon: LayoutGrid }
	};
	/** Narrower than this, a document starts with one page in a row. */
	const NARROW = 560;
	/** The zoom has come to rest when nothing changed it for this long. */
	const REST = 150;

	let container = $state<HTMLDivElement | null>(null);
	let zoom = $state(1);
	let layout = $state<Layout | null>('two');
	let current = $state(1);
	let last = $state(1);
	// Plain bookkeeping, nothing in the markup reads these.
	// The layout a second double click returns to.
	let back: Layout = 'two';
	let fitted = false;
	let width = 0;
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const nodes = new Map<number, HTMLElement>();
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const inView = new Set<number>();
	let observer: IntersectionObserver | null = null;
	let observed: Element | null | undefined;
	let resting: ReturnType<typeof setTimeout> | undefined;

	const widest = $derived(sizes.reduce((most, size) => Math.max(most, size.width), 1));
	$effect(() => onpage?.(current, sizes.length));

	function room(): Room {
		if (!container) return { width: 800, padding: 24, gap: 12 };
		const style = getComputedStyle(container);
		return {
			width: container.clientWidth,
			padding: parseFloat(style.paddingLeft) + parseFloat(style.paddingRight),
			gap: parseFloat(style.columnGap) || 0
		};
	}

	/** Whether the viewer scrolls itself: on narrow screens it is as tall as its pages, and the
	 * window scrolls. */
	function scrollsItself(): boolean {
		return !!container && container.scrollHeight > container.clientHeight + 1;
	}

	/** The visible part of the viewer, in client coordinates. */
	function view(): { left: number; top: number; width: number; bottom: number } {
		const rect = container!.getBoundingClientRect();
		return {
			left: rect.left,
			width: rect.width,
			top: Math.max(rect.top, 0),
			bottom: Math.min(rect.bottom, window.innerHeight)
		};
	}

	/** The middle of the view, a third down: where the buttons and keys zoom around. */
	function center(): Point {
		const seen = view();
		return { x: seen.left + seen.width / 2, y: seen.top + (seen.bottom - seen.top) / 3 };
	}

	// The first fit, once the pages and the room are known: two pages, one on a narrow screen.
	$effect(() => {
		if (fitted || !container || sizes.length === 0) return;
		fitted = true;
		const start: Layout = container.clientWidth < NARROW ? 'one' : 'two';
		layout = start;
		zoom = fitZoom(start, room(), widest);
		void tick().then(() => {
			observe();
			follow();
		});
	});

	/** The spot under `point`: on the page there, else on the page in view. */
	function anchorAt(point: Point): Anchor | null {
		const hit = document.elementFromPoint(point.x, point.y)?.closest<HTMLElement>('[data-page]');
		const number = hit && container?.contains(hit) ? Number(hit.dataset.page) : current;
		const node = nodes.get(number);
		return node ? anchorOn(number, node.getBoundingClientRect(), point) : null;
	}

	/** Zoom to `next` (within bounds), keeping the spot under `point` where it is. The layout
	 * is `chosen`, else the one the zoom reaches. */
	async function zoomTo(next: number, point: Point | null, chosen: Layout | null = null) {
		if (!container) return;
		const space = room();
		const anchor = point ? anchorAt(point) : null;
		zoom = bounded(next, space, widest);
		layout = chosen ?? layoutAt(zoom, space, widest);
		restSoon();
		if (!anchor) return;
		await tick();
		const node = nodes.get(anchor.page);
		if (!node || !container) return;
		const shift = shiftFor(anchor, node.getBoundingClientRect());
		container.scrollLeft += shift.x;
		if (scrollsItself()) container.scrollTop += shift.y;
		else window.scrollBy(0, shift.y);
	}

	function choose(next: Layout) {
		if (next !== 'one') back = next;
		void zoomTo(fitZoom(next, room(), widest), center(), next);
	}

	function enlarge(event: MouseEvent) {
		if (!(event.target as Element).closest('[data-page]')) return;
		const point = { x: event.clientX, y: event.clientY };
		if (layout === 'one') {
			void zoomTo(fitZoom(back, room(), widest), point, back);
		} else {
			back = layout ?? 'two';
			void zoomTo(fitZoom('one', room(), widest), point, 'one');
		}
	}

	function keydown(event: KeyboardEvent) {
		// Ctrl/⌘ + and − zoom the browser; Alt + a key is a shortcut of the system or the browser.
		if (event.ctrlKey || event.metaKey || event.altKey) return;
		if (event.key === '+' || event.key === '=') void zoomTo(zoom * 1.25, center());
		else if (event.key === '-') void zoomTo(zoom / 1.25, center());
		else if (event.key === '0') choose('two');
	}

	/** The page shown in the upper third of the view: the first of its row. */
	function follow() {
		if (!container || sizes.length === 0) return;
		const seen = view();
		const line = seen.top + (seen.bottom - seen.top) / 3;
		const tops = sizes.map(
			(_, index) => nodes.get(index + 1)?.getBoundingClientRect().top ?? Infinity
		);
		({ first: current, last } = rowAt(tops, line));
	}

	/** Scroll so that the place stands in the upper third of the view, and in sight sideways. */
	export function reveal(place: Place) {
		const node = nodes.get(place.page);
		if (!container || !node) return;
		const box = place.boxes[0];
		const rect = node.getBoundingClientRect();
		const seen = view();
		const y = rect.top + (box?.y ?? 0) * rect.height;
		const x = rect.left + ((box?.x ?? 0) + (box?.width ?? 0) / 2) * rect.width;
		const left =
			container.scrollWidth > container.clientWidth + 1 ? x - (seen.left + seen.width / 2) : 0;
		if (scrollsItself()) {
			const top = y - (container.getBoundingClientRect().top + container.clientHeight / 3);
			container.scrollBy({ left, top, behavior: 'smooth' });
		} else {
			if (left) container.scrollBy({ left, behavior: 'smooth' });
			window.scrollBy({ top: y - window.innerHeight / 3, behavior: 'smooth' });
		}
	}

	/** Watch which pages are near the view: in the viewer where it scrolls, else in the window. */
	function observe() {
		const root = scrollsItself() ? container : null;
		if (observer && root === observed) return;
		observer?.disconnect();
		observed = root;
		inView.clear();
		observer = new IntersectionObserver(seen, { root, rootMargin: '300px' });
		for (const node of nodes.values()) observer.observe(node);
	}

	function seen(entries: IntersectionObserverEntry[]) {
		for (const entry of entries) {
			const node = entry.target as HTMLElement;
			const number = Number(node.dataset.page);
			if (!entry.isIntersecting) {
				inView.delete(number);
				continue;
			}
			inView.add(number);
			// While the zoom moves, the pages wait for it to rest.
			if (resting === undefined) onshow?.(number, node);
		}
	}

	function restSoon() {
		clearTimeout(resting);
		resting = setTimeout(() => {
			resting = undefined;
			observe();
			follow();
			const pages = [...inView].flatMap((number) => {
				const node = nodes.get(number);
				return node ? [{ number, node }] : [];
			});
			onsettle?.(pages);
		}, REST);
	}

	function watch(node: HTMLElement, number: number) {
		node.dataset.page = String(number);
		nodes.set(number, node);
		observer?.observe(node);
		return {
			destroy() {
				observer?.unobserve(node);
				nodes.delete(number);
				inView.delete(number);
			}
		};
	}

	// A wider or narrower viewer (window, panel): a chosen layout keeps its number of pages.
	function resized() {
		if (!container) return;
		const next = container.clientWidth;
		if (Math.abs(next - width) < 2) return;
		width = next;
		if (!fitted) return;
		const space = room();
		if (layout) zoom = fitZoom(layout, space, widest);
		else {
			zoom = bounded(zoom, space, widest);
			layout = layoutAt(zoom, space, widest);
		}
		restSoon();
	}

	onMount(() => {
		const watcher = new ResizeObserver(resized);
		if (container) {
			width = container.clientWidth;
			watcher.observe(container);
		}
		return () => {
			watcher.disconnect();
			clearTimeout(resting);
			observer?.disconnect();
		};
	});
</script>

<svelte:window onscroll={follow} />

<div class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-surface">
	<div
		role="toolbar"
		aria-label={m.pdf_toolbar()}
		class="@container flex flex-wrap items-center gap-x-2 gap-y-1 border-b bg-card px-3 py-2"
	>
		<IconButton onclick={() => zoomTo(zoom / 1.25, center())} label={m.pdf_zoom_out()}>
			<Minus aria-hidden="true" />
		</IconButton>
		<button
			type="button"
			class="min-w-14 rounded-full px-2 py-1.5 text-center text-sm tabular-nums hover:bg-accent"
			aria-label={m.pdf_zoom_reset()}
			title={m.pdf_zoom_reset()}
			onclick={() => choose('two')}
		>
			{Math.round(zoom * 100)} %
		</button>
		<IconButton onclick={() => zoomTo(zoom * 1.25, center())} label={m.pdf_zoom_in()}>
			<Plus aria-hidden="true" />
		</IconButton>
		<Separator orientation="vertical" class="mx-1 h-5 self-center" />
		<Segmented
			size="sm"
			names="@3xl"
			label={m.pdf_layouts()}
			value={layout ?? ''}
			options={LAYOUTS.map((entry) => ({
				value: entry,
				label: NAMES[entry].label(),
				hint: NAMES[entry].hint(),
				icon: NAMES[entry].icon
			}))}
			onchange={(next) => choose(next as Layout)}
		/>
		<span class="ml-auto text-sm text-muted-foreground">
			{#if note}{note} ·{/if}
			{last > current
				? m.pdf_pages({ first: current, last, total: sizes.length })
				: m.pdf_page({ current, total: sizes.length })}
		</span>
		{@render end?.()}
	</div>
	<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
	<div
		bind:this={container}
		role="document"
		tabindex="0"
		aria-label={label}
		onkeydown={keydown}
		onscroll={follow}
		ondblclick={enlarge}
		use:zoomGestures={{ zoom: () => zoom, zoomTo: (next, point) => void zoomTo(next, point) }}
		class="justify-[safe_center] relative flex min-h-[24rem] flex-1 touch-pan-x touch-pan-y [scrollbar-gutter:stable] flex-wrap content-start gap-3 overflow-auto p-3"
	>
		{#if loading}
			<p class="w-full py-16 text-center text-muted-foreground">{m.loading()}</p>
		{:else if problem}
			<p class="w-full py-16 text-center text-destructive" role="alert">{problem}</p>
		{:else}
			{#each sizes as size, index (index)}
				<div
					use:watch={index + 1}
					class="relative shrink-0 bg-white shadow-sm select-none"
					style:width={`${size.width * zoom}px`}
					style:height={`${size.height * zoom}px`}
				>
					{@render page(index + 1)}
					{#each marks.filter((mark) => mark.page === index + 1) as mark, markIndex (`${mark.key}-${markIndex}`)}
						{#each mark.boxes as box, boxIndex (boxIndex)}
							<div
								class={cn(
									'pointer-events-none absolute rounded-xs transition-shadow',
									mark.derived
										? 'bg-primary/10 outline-2 outline-offset-1 outline-primary outline-dashed'
										: 'bg-primary/20 ring-2 ring-primary',
									mark.pinned && 'shadow-pinned'
								)}
								style:left={`${box.x * 100}%`}
								style:top={`${box.y * 100}%`}
								style:width={`${box.width * 100}%`}
								style:height={`${box.height * 100}%`}
								aria-hidden="true"
							>
								{#if boxIndex === 0}
									<span
										class="absolute bottom-full left-0 mb-1 rounded-md bg-primary px-1.5 text-nano leading-4 font-semibold whitespace-nowrap text-primary-foreground"
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
