/**
 * Zooming the pages of a document. Pages stand side by side and wrap into rows; their width
 * follows the zoom (1 is a page's natural size), so the zoom decides how many fit in a row.
 * Three layouts name the usual ones: one page, two pages, the overview (four in a row), which
 * is as far out as the zoom goes. Zooming keeps the spot under the pointer where it is.
 */

export type Layout = 'one' | 'two' | 'overview';
export const LAYOUTS: readonly Layout[] = ['one', 'two', 'overview'];
export const COLUMNS: Record<Layout, number> = { one: 1, two: 2, overview: 4 };
/** As far in as the zoom goes. */
export const MOST_ZOOM = 4;
/** A zoom this close to a layout's counts as that layout. */
const NEAR = 0.03;

/** The room of the viewer: its inner width, its padding left and right, the gap of a row. */
export interface Room {
	width: number;
	padding: number;
	gap: number;
}

export interface Point {
	x: number;
	y: number;
}

/** A rectangle in client coordinates, as `getBoundingClientRect` gives it. */
export interface Rect {
	left: number;
	top: number;
	width: number;
	height: number;
}

/** The zoom at which `layout`'s number of pages, `pageWidth` wide at 1, fills a row. */
export function fitZoom(layout: Layout, room: Room, pageWidth: number): number {
	const columns = COLUMNS[layout];
	// A pixel spare: rounding must not push the last page into the next row.
	const free = room.width - room.padding - (columns - 1) * room.gap - 1;
	return Math.max(0.01, free / columns / pageWidth);
}

/** The layout `zoom` is (within 3 %), or null. */
export function layoutAt(zoom: number, room: Room, pageWidth: number): Layout | null {
	for (const layout of LAYOUTS) {
		const fit = fitZoom(layout, room, pageWidth);
		if (Math.abs(zoom - fit) / fit <= NEAR) return layout;
	}
	return null;
}

/** `zoom` within its bounds: out to the overview, in to `MOST_ZOOM`. */
export function bounded(zoom: number, room: Room, pageWidth: number): number {
	const least = fitZoom('overview', room, pageWidth);
	return Math.max(least, Math.min(Math.max(least, MOST_ZOOM), zoom));
}

/** How much one wheel event zooms: a mouse notch about a third, a pinch on a trackpad (many
 * small events) a little each. */
export function wheelFactor(event: { deltaY: number; deltaMode: number }): number {
	const pixels =
		event.deltaMode === 1
			? event.deltaY * 16
			: event.deltaMode === 2
				? event.deltaY * 400
				: event.deltaY;
	const delta = Math.max(-40, Math.min(40, pixels));
	return Math.exp(-delta / 100);
}

/** A spot on a page: its page, where on it (fractions of its width and height), and the point
 * of the window it should stay under. */
export interface Anchor {
	page: number;
	fx: number;
	fy: number;
	at: Point;
}

/** The spot under `point` on page `page`, which stands at `rect`. */
export function anchorOn(page: number, rect: Rect, point: Point): Anchor {
	return {
		page,
		fx: rect.width > 0 ? (point.x - rect.left) / rect.width : 0,
		fy: rect.height > 0 ? (point.y - rect.top) / rect.height : 0,
		at: point
	};
}

/** How far to scroll so that the anchor's spot, its page now at `rect`, is under its point again. */
export function shiftFor(anchor: Anchor, rect: Rect): Point {
	return {
		x: rect.left + anchor.fx * rect.width - anchor.at.x,
		y: rect.top + anchor.fy * rect.height - anchor.at.y
	};
}

/** The row of pages that stands at `line`: its first and last page; the pages' tops in order,
 * from 1. */
export function rowAt(tops: readonly number[], line: number): { first: number; last: number } {
	let first = 1;
	let row = -Infinity;
	tops.forEach((top, index) => {
		if (top <= line && top > row + 1) {
			row = top;
			first = index + 1;
		}
	});
	let last = first;
	while (last < tops.length && Math.abs(tops[last] - tops[first - 1]) <= 1) last += 1;
	return { first, last };
}
