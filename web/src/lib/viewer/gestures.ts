/**
 * Zooming by gesture over an element: Ctrl or ⌘ with the mouse wheel and a pinch on a trackpad
 * (browsers report it as a wheel turn with Ctrl), Safari's own gesture events, and two fingers
 * on a touch screen. Plain scrolling stays scrolling. An action: `use:zoomGestures={target}`.
 */
import { type Point, wheelFactor } from './zoom.ts';

export interface ZoomTarget {
	/** The zoom now. */
	zoom: () => number;
	/** Zoom to `next`, keeping the spot under `point` where it is. */
	zoomTo: (next: number, point: Point) => void;
}

/** Safari's gesture events (not in the DOM's types). */
interface GestureEvent extends UIEvent {
	scale: number;
	clientX: number;
	clientY: number;
}

function spread(touches: TouchList): number {
	return Math.hypot(
		touches[0].clientX - touches[1].clientX,
		touches[0].clientY - touches[1].clientY
	);
}

function middle(touches: TouchList): Point {
	return {
		x: (touches[0].clientX + touches[1].clientX) / 2,
		y: (touches[0].clientY + touches[1].clientY) / 2
	};
}

export function zoomGestures(node: HTMLElement, initial: ZoomTarget) {
	let target = initial;
	// The zoom a gesture started at, and for two fingers their spread then.
	let gesture: number | null = null;
	let pinch: { spread: number; zoom: number } | null = null;

	function wheel(event: WheelEvent) {
		if (!event.ctrlKey && !event.metaKey) return;
		event.preventDefault();
		target.zoomTo(target.zoom() * wheelFactor(event), { x: event.clientX, y: event.clientY });
	}
	function gestureStart(event: Event) {
		event.preventDefault();
		gesture = target.zoom();
	}
	function gestureChange(event: Event) {
		event.preventDefault();
		const { scale, clientX, clientY } = event as GestureEvent;
		if (gesture !== null) target.zoomTo(gesture * scale, { x: clientX, y: clientY });
	}
	function gestureEnd() {
		gesture = null;
	}
	function touchStart(event: TouchEvent) {
		if (event.touches.length === 2) pinch = { spread: spread(event.touches), zoom: target.zoom() };
	}
	function touchMove(event: TouchEvent) {
		if (event.touches.length !== 2 || !pinch) return;
		event.preventDefault();
		target.zoomTo((pinch.zoom * spread(event.touches)) / pinch.spread, middle(event.touches));
	}
	function touchEnd(event: TouchEvent) {
		if (event.touches.length < 2) pinch = null;
	}

	node.addEventListener('wheel', wheel, { passive: false });
	node.addEventListener('gesturestart', gestureStart);
	node.addEventListener('gesturechange', gestureChange);
	node.addEventListener('gestureend', gestureEnd);
	node.addEventListener('touchstart', touchStart, { passive: true });
	node.addEventListener('touchmove', touchMove, { passive: false });
	node.addEventListener('touchend', touchEnd);
	node.addEventListener('touchcancel', touchEnd);
	return {
		update(next: ZoomTarget) {
			target = next;
		},
		destroy() {
			node.removeEventListener('wheel', wheel);
			node.removeEventListener('gesturestart', gestureStart);
			node.removeEventListener('gesturechange', gestureChange);
			node.removeEventListener('gestureend', gestureEnd);
			node.removeEventListener('touchstart', touchStart);
			node.removeEventListener('touchmove', touchMove);
			node.removeEventListener('touchend', touchEnd);
			node.removeEventListener('touchcancel', touchEnd);
		}
	};
}
