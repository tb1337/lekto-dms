import { describe, expect, it, vi } from 'vitest';
import { zoomGestures } from './gestures.ts';

function setup(zoom = 1) {
	const node = document.createElement('div');
	const zoomTo = vi.fn();
	const action = zoomGestures(node, { zoom: () => zoom, zoomTo });
	return { node, zoomTo, action };
}

describe('zoom gestures', () => {
	it('zooms with Ctrl or ⌘ and the wheel, around the pointer, and keeps the browser out', () => {
		const { node, zoomTo } = setup();
		const event = new WheelEvent('wheel', {
			deltaY: -100,
			ctrlKey: true,
			clientX: 40,
			clientY: 60,
			cancelable: true
		});
		node.dispatchEvent(event);
		expect(event.defaultPrevented).toBe(true);
		expect(zoomTo).toHaveBeenCalledWith(Math.exp(0.4), { x: 40, y: 60 });
		node.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, metaKey: true, cancelable: true }));
		expect(zoomTo).toHaveBeenLastCalledWith(Math.exp(-0.4), { x: 0, y: 0 });
	});

	it('leaves plain scrolling alone', () => {
		const { node, zoomTo } = setup();
		const event = new WheelEvent('wheel', { deltaY: 100, cancelable: true });
		node.dispatchEvent(event);
		expect(event.defaultPrevented).toBe(false);
		expect(zoomTo).not.toHaveBeenCalled();
	});

	it('follows Safari’s pinch from the zoom it started at', () => {
		const { node, zoomTo } = setup(0.5);
		const gesture = (type: string, scale: number) =>
			Object.assign(new Event(type, { cancelable: true }), { scale, clientX: 10, clientY: 20 });
		node.dispatchEvent(gesture('gesturestart', 1));
		node.dispatchEvent(gesture('gesturechange', 2));
		expect(zoomTo).toHaveBeenLastCalledWith(1, { x: 10, y: 20 });
	});

	it('stops listening when it is destroyed', () => {
		const { node, zoomTo, action } = setup();
		action.destroy();
		node.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, ctrlKey: true, cancelable: true }));
		expect(zoomTo).not.toHaveBeenCalled();
	});
});
