import { describe, expect, it } from 'vitest';
import {
	anchorOn,
	bounded,
	fitZoom,
	layoutAt,
	MOST_ZOOM,
	rowAt,
	shiftFor,
	wheelFactor,
	type Room
} from './zoom.ts';

// A viewer 1000 px wide inside, 24 px of padding, 12 px between pages; A4 is 793 px at 100 %.
const ROOM: Room = { width: 1024, padding: 24, gap: 12 };
const A4 = 793;

describe('layouts', () => {
	it('fits a layout’s number of pages into a row', () => {
		for (const [layout, columns] of [
			['one', 1],
			['two', 2],
			['overview', 4]
		] as const) {
			const width = fitZoom(layout, ROOM, A4) * A4;
			expect(columns * width + (columns - 1) * ROOM.gap).toBeLessThanOrEqual(1000);
			expect(columns * width + (columns - 1) * ROOM.gap).toBeGreaterThan(998);
		}
	});

	it('knows a layout when the zoom reaches it, within 3 %', () => {
		const two = fitZoom('two', ROOM, A4);
		expect(layoutAt(two, ROOM, A4)).toBe('two');
		expect(layoutAt(two * 1.02, ROOM, A4)).toBe('two');
		expect(layoutAt(two * 1.1, ROOM, A4)).toBeNull();
		expect(layoutAt(fitZoom('overview', ROOM, A4), ROOM, A4)).toBe('overview');
	});

	it('zooms out to the overview at most, in to 400 %', () => {
		const overview = fitZoom('overview', ROOM, A4);
		expect(bounded(overview / 2, ROOM, A4)).toBe(overview);
		expect(bounded(9, ROOM, A4)).toBe(MOST_ZOOM);
		expect(bounded(1, ROOM, A4)).toBe(1);
	});
});

describe('gestures', () => {
	it('zooms a mouse notch about a third, a pinch step a little', () => {
		expect(wheelFactor({ deltaY: -100, deltaMode: 0 })).toBeCloseTo(Math.exp(0.4));
		expect(wheelFactor({ deltaY: 3, deltaMode: 1 })).toBeCloseTo(Math.exp(-0.4));
		expect(wheelFactor({ deltaY: 2, deltaMode: 0 })).toBeCloseTo(0.98, 2);
	});

	it('keeps the spot under the pointer where it is', () => {
		const before = { left: 100, top: 50, width: 400, height: 566 };
		const anchor = anchorOn(3, before, { x: 300, y: 191.5 });
		expect([anchor.fx, anchor.fy]).toEqual([0.5, 0.25]);
		// Twice as large, moved by the new layout: scroll by what the spot moved.
		const after = { left: 20, top: 400, width: 800, height: 1132 };
		expect(shiftFor(anchor, after)).toEqual({ x: 120, y: 491.5 });
	});

	it('names the row of pages at the line', () => {
		// Two in a row: pages 1 and 2 at 0, 3 and 4 at 600, 5 at 1200.
		const tops = [0, 0, 600, 600, 1200];
		expect(rowAt(tops, 300)).toEqual({ first: 1, last: 2 });
		expect(rowAt(tops, 700)).toEqual({ first: 3, last: 4 });
		expect(rowAt(tops, 5000)).toEqual({ first: 5, last: 5 });
	});
});
