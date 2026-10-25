import { fireEvent, render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import PageViewer from './PageViewer.svelte';

// jsdom lays nothing out: the viewer gets a width and its paddings by hand.
let clientWidth: PropertyDescriptor | undefined;

beforeEach(() => {
	clientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
	Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 800 });
	vi.spyOn(window, 'getComputedStyle').mockReturnValue({
		paddingLeft: '12px',
		paddingRight: '12px',
		columnGap: '12px'
	} as CSSStyleDeclaration);
	// Zooming looks for the page under the pointer.
	document.elementFromPoint ??= () => null;
	vi.stubGlobal(
		'IntersectionObserver',
		class {
			observe() {}
			unobserve() {}
			disconnect() {}
		}
	);
});

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	if (clientWidth) Object.defineProperty(HTMLElement.prototype, 'clientWidth', clientWidth);
});

const page = createRawSnippet(() => ({ render: () => '<span></span>' }));

describe('PageViewer', () => {
	it('zooms with + and − but leaves the browser its shortcuts with Ctrl, ⌘ or Alt', async () => {
		render(PageViewer, { sizes: [{ width: 600, height: 800 }], label: 'PDF', page });
		const view = screen.getByRole('document');
		const zoom = () => screen.getByTitle(m.pdf_zoom_reset()).textContent?.trim();
		const before = zoom();
		await fireEvent.keyDown(view, { key: '+', ctrlKey: true });
		await fireEvent.keyDown(view, { key: '-', metaKey: true });
		await fireEvent.keyDown(view, { key: '0', altKey: true });
		expect(zoom()).toBe(before);
		await fireEvent.keyDown(view, { key: '+' });
		expect(zoom()).not.toBe(before);
	});
});
