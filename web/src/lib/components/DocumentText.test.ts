import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import DocumentText from './DocumentText.svelte';

afterEach(() => vi.unstubAllGlobals());

function answer(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: {
			'content-type': status === 200 ? 'application/json' : 'application/problem+json'
		}
	});
}

describe('DocumentText', () => {
	it('shows the text once it is parsed and loads the rest on request', async () => {
		const fetchMock = vi.fn<(request: Request) => Promise<Response>>(async (request) => {
			const offset = new URL(request.url).searchParams.get('offset');
			if (offset === '0')
				return answer({ text: 'Rechnung ', offset: 0, total_length: 12, next_offset: 9 });
			return answer({ text: '4711', offset: 9, total_length: 12, next_offset: null });
		});
		vi.stubGlobal('fetch', fetchMock);
		render(DocumentText, { documentId: 'd1' });
		const first = await screen.findByText('Rechnung');
		expect(first.tagName).toBe('PRE');
		await screen.getByText(m.text_more()).click();
		await screen.findByText('Rechnung 4711');
		expect(screen.queryByText(m.text_more())).toBeNull();
	});

	it('says so while the document has no text yet', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => answer({ title: 'conflict', status: 409, detail: 'no text yet' }, 409))
		);
		render(DocumentText, { documentId: 'd2' });
		await screen.findByText(m.text_none());
		expect(screen.queryByRole('alert')).toBeNull();
	});
});
