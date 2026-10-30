/**
 * A document's link that shows it first (web/DESIGN.md, "Beam"): a click, a tap or Enter
 * `view`s it (the Beam), a double click or a long press (a phone) `open`s it. A click with a
 * modifier key, the middle button and the browser's menu keep the link's own ways (a new tab).
 * A mouse's first click waits for a second one that may follow, so that a double click goes
 * straight to the document without the Beam in between.
 */
import type { Attachment } from 'svelte/attachments';

/** How long a mouse's click waits for a second one, and a finger holds for a long press. */
export const DOUBLE_MS = 250;
export const LONG_MS = 500;
// How far a finger may move and still press long (else it scrolls).
const SLOP = 10;

export function viewOrOpen(view: () => void, open: () => void): Attachment<HTMLElement> {
	return (element) => {
		let waiting: ReturnType<typeof setTimeout> | undefined;
		let holding: ReturnType<typeof setTimeout> | undefined;
		let start: { x: number; y: number } | null = null;
		let touch = false;
		// A long press opened it: the click its release may still bring does nothing.
		let pressed = false;

		const stop = () => {
			clearTimeout(waiting);
			clearTimeout(holding);
			waiting = holding = undefined;
			start = null;
		};

		function click(event: MouseEvent) {
			const own =
				event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
			if (event.defaultPrevented || own) return;
			event.preventDefault();
			if (pressed) {
				pressed = false;
				return;
			}
			if (event.detail >= 2) {
				stop();
				open();
			} else if (event.detail === 0 || touch) {
				view();
			} else {
				clearTimeout(waiting);
				waiting = setTimeout(view, DOUBLE_MS);
			}
		}

		function down(event: PointerEvent) {
			touch = event.pointerType === 'touch';
			pressed = false;
			if (!touch || !event.isPrimary) return;
			start = { x: event.clientX, y: event.clientY };
			clearTimeout(holding);
			holding = setTimeout(() => {
				pressed = true;
				stop();
				open();
			}, LONG_MS);
		}

		function move(event: PointerEvent) {
			if (!start) return;
			if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > SLOP) {
				clearTimeout(holding);
				start = null;
			}
		}

		function release() {
			clearTimeout(holding);
			start = null;
		}

		// A finger's long press is ours, not the browser's menu.
		function menu(event: Event) {
			if (touch && (pressed || start)) event.preventDefault();
		}

		element.addEventListener('click', click);
		element.addEventListener('pointerdown', down);
		element.addEventListener('pointermove', move);
		element.addEventListener('pointerup', release);
		element.addEventListener('pointercancel', release);
		element.addEventListener('contextmenu', menu);
		return () => {
			stop();
			element.removeEventListener('click', click);
			element.removeEventListener('pointerdown', down);
			element.removeEventListener('pointermove', move);
			element.removeEventListener('pointerup', release);
			element.removeEventListener('pointercancel', release);
			element.removeEventListener('contextmenu', menu);
		};
	};
}
