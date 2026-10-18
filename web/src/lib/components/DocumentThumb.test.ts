import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import DocumentThumb from './DocumentThumb.svelte';

describe('DocumentThumb', () => {
	it('shows the preview of a document with page images', () => {
		const { container } = render(DocumentThumb, { id: 'doc-1', pages: 2 });
		expect(container.querySelector('img')?.getAttribute('src')).toBe(
			'/api/v1/documents/doc-1/preview'
		);
	});

	it('asks for no preview while there are no page images', () => {
		const { container } = render(DocumentThumb, { id: 'doc-1', pages: null });
		expect(container.querySelector('img')).toBeNull();
		expect(container.querySelector('svg')).not.toBeNull();
	});
});
