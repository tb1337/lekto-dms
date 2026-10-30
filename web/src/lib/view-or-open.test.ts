import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DOUBLE_MS, LONG_MS, viewOrOpen } from './view-or-open.ts';

let link: HTMLAnchorElement;
let detach: () => void;
const view = vi.fn();
const open = vi.fn();

function click(detail: number, init: MouseEventInit = {}): MouseEvent {
	const event = new MouseEvent('click', { bubbles: true, cancelable: true, detail, ...init });
	link.dispatchEvent(event);
	return event;
}

function pointer(type: string, pointerType: string, x = 10, y = 10) {
	link.dispatchEvent(
		new PointerEvent(type, {
			bubbles: true,
			cancelable: true,
			pointerType,
			isPrimary: true,
			clientX: x,
			clientY: y
		})
	);
}

beforeEach(() => {
	vi.useFakeTimers();
	link = document.createElement('a');
	link.href = '/ui/documents/doc-1';
	document.body.append(link);
	detach = viewOrOpen(view, open)(link) as () => void;
});

afterEach(() => {
	detach();
	link.remove();
	view.mockClear();
	open.mockClear();
	vi.useRealTimers();
});

describe('a link that shows a document first', () => {
	it('shows it on a click, once no second click followed', () => {
		pointer('pointerdown', 'mouse');
		expect(click(1).defaultPrevented).toBe(true);
		expect(view).not.toHaveBeenCalled();
		vi.advanceTimersByTime(DOUBLE_MS);
		expect(view).toHaveBeenCalledOnce();
		expect(open).not.toHaveBeenCalled();
	});

	it('opens it on a double click, without showing it first', () => {
		pointer('pointerdown', 'mouse');
		click(1);
		pointer('pointerdown', 'mouse');
		click(2);
		vi.advanceTimersByTime(DOUBLE_MS);
		expect(open).toHaveBeenCalledOnce();
		expect(view).not.toHaveBeenCalled();
	});

	it('shows it at once on Enter and on a tap', () => {
		click(0);
		expect(view).toHaveBeenCalledOnce();
		pointer('pointerdown', 'touch');
		pointer('pointerup', 'touch');
		click(1);
		expect(view).toHaveBeenCalledTimes(2);
		vi.advanceTimersByTime(LONG_MS);
		expect(open).not.toHaveBeenCalled();
	});

	it('opens it on a long press, and ignores the click its release brings', () => {
		pointer('pointerdown', 'touch');
		const menu = new Event('contextmenu', { cancelable: true });
		link.dispatchEvent(menu);
		expect(menu.defaultPrevented).toBe(true);
		vi.advanceTimersByTime(LONG_MS);
		expect(open).toHaveBeenCalledOnce();
		pointer('pointerup', 'touch');
		click(1);
		expect(view).not.toHaveBeenCalled();
	});

	it('lets a finger that moves scroll', () => {
		pointer('pointerdown', 'touch');
		pointer('pointermove', 'touch', 10, 40);
		vi.advanceTimersByTime(LONG_MS);
		expect(open).not.toHaveBeenCalled();
	});

	it('leaves a click with a modifier key to the link (a new tab)', () => {
		expect(click(1, { ctrlKey: true }).defaultPrevented).toBe(false);
		expect(click(1, { metaKey: true }).defaultPrevented).toBe(false);
		vi.advanceTimersByTime(DOUBLE_MS);
		expect(view).not.toHaveBeenCalled();
	});
});
