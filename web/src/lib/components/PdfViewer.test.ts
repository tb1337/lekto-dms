import { render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PdfViewer from './PdfViewer.svelte';

// pdf.js needs a worker and a canvas; the test watches only how a document is opened and
// dropped.
const pdfjs = vi.hoisted(() => ({
	getDocument: vi.fn(),
	GlobalWorkerOptions: { workerSrc: '' }
}));
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => pdfjs);
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }));

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((done) => (resolve = done));
	return { promise, resolve };
}

function task() {
	const opened = deferred<{ numPages: number }>();
	return {
		promise: opened.promise,
		destroy: vi.fn(async () => {}),
		open: () => opened.resolve({ numPages: 0 })
	};
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const SOURCES = ['/api/v1/documents/d1/archive'];

beforeEach(() => {
	pdfjs.getDocument.mockReset();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('PdfViewer', () => {
	it('opens no document when the viewer closed while the file was on its way', async () => {
		const download = deferred<Response>();
		vi.stubGlobal(
			'fetch',
			vi.fn(() => download.promise)
		);
		const { unmount } = render(PdfViewer, { sources: SOURCES, label: 'PDF' });
		unmount();
		download.resolve(new Response(new Uint8Array([1, 2, 3])));
		await settle();
		expect(pdfjs.getDocument).not.toHaveBeenCalled();
	});

	it('drops a document that finished opening after the viewer closed', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response(new Uint8Array([1, 2, 3])))
		);
		const loading = task();
		pdfjs.getDocument.mockReturnValue(loading);
		const { unmount } = render(PdfViewer, { sources: SOURCES, label: 'PDF' });
		await vi.waitFor(() => expect(pdfjs.getDocument).toHaveBeenCalledOnce());
		unmount();
		loading.open();
		await settle();
		expect(loading.destroy).toHaveBeenCalled();
	});
});
