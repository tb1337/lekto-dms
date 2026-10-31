// One box of help at a time (web/DESIGN.md, "Help and tooltips"; Tobi, 31.10.2026): a tooltip or
// an info tip that opens closes the one shown before, at once. While one shows, or just showed,
// the next one shows without its delay, as the tooltips of an operating system do. A focus
// opens a tooltip only when Tab brought it, not when a dialog or the Beam hands it back to the
// button that opened them; a pointer resting where it clicked opens none.

/** A box of help, by the way it closes. */
export interface Tip {
	close: () => void;
}

/** How long after a box closed the next one still shows at once. */
const WARM_MS = 300;

let shown: Tip | null = null;
let cooling: ReturnType<typeof setTimeout> | undefined;
const state = $state({ warm: false });

/** Whether a box shows or just showed: the next one skips its delay. */
export function warm(): boolean {
	return state.warm;
}

/** `tip` opened: the one shown before closes. */
export function showTip(tip: Tip): void {
	if (shown === tip) return;
	const before = shown;
	shown = tip;
	clearTimeout(cooling);
	state.warm = true;
	before?.close();
}

/** `tip` closed; the next one shows at once for a moment. */
export function hideTip(tip: Tip): void {
	if (shown !== tip) return;
	shown = null;
	clearTimeout(cooling);
	cooling = setTimeout(() => (state.warm = false), WARM_MS);
}

// A focus counts as the keyboard's while Tab moves it: the browser moves the focus within the
// task of the key, so the mark lasts until the next one. `focusing` marks a focus while its
// event runs, for `mayOpenTip` to tell a focus from a pointer. `pressed` is where the pointer
// pressed, until it moves away: a pointer resting after a click opens no tooltip, also when a
// dialog it opened closes again beneath it.
let tabbing = false;
let focusing: { byTab: boolean } | null = null;
let pressed: { x: number; y: number } | null = null;
/** How far the pointer moves before it counts as moved since it pressed. */
const MOVED_PX = 4;

if (typeof document !== 'undefined') {
	window.addEventListener(
		'pointerdown',
		(event) => (pressed = { x: event.clientX, y: event.clientY }),
		true
	);
	window.addEventListener(
		'pointermove',
		(event) => {
			if (pressed && Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > MOVED_PX) {
				pressed = null;
			}
		},
		true
	);
	window.addEventListener(
		'keydown',
		(event) => {
			if (event.key !== 'Tab') return;
			tabbing = true;
			setTimeout(() => (tabbing = false));
		},
		true
	);
	document.addEventListener(
		'focus',
		() => {
			focusing = { byTab: tabbing };
			setTimeout(() => (focusing = null));
		},
		true
	);
}

/** Whether a tooltip may open now: on a focus Tab brought, not on one handed back by a dialog or
 * set by a script; on hover, once the pointer moved since it last pressed. */
export function mayOpenTip(): boolean {
	if (focusing !== null) return focusing.byTab;
	return pressed === null;
}
