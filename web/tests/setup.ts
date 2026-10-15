import { vi } from 'vitest';

// jsdom lacks a few browser APIs the components use.

if (!window.matchMedia) {
	window.matchMedia = (query: string) =>
		({
			matches: false,
			media: query,
			onchange: null,
			addListener: () => {},
			removeListener: () => {},
			addEventListener: () => {},
			removeEventListener: () => {},
			dispatchEvent: () => false
		}) as MediaQueryList;
}

if (!window.ResizeObserver) {
	window.ResizeObserver = class {
		observe() {}
		unobserve() {}
		disconnect() {}
	};
}

if (!Element.prototype.scrollIntoView) {
	Element.prototype.scrollIntoView = () => {};
}

// CodeMirror reads the selection in a shadow root through it where `getSelection` is missing.
if (!document.execCommand) {
	document.execCommand = () => false;
}

// CodeMirror needs a browser's layout; component tests edit templates in a plain text area.
vi.mock('#lib/templates/codemirror.ts', () => import('#lib/testing/fake-template-editor.ts'));
