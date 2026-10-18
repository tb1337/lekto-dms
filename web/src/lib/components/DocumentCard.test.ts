import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import { listedOf } from '#lib/testing/documents.ts';
import DocumentCard from './DocumentCard.svelte';
import DocumentRow from './DocumentRow.svelte';
import InboxMark from './InboxMark.svelte';

type Listed = components['schemas']['ListedDocument'];

function listed(changes: Partial<Listed> = {}): Listed {
	return listedOf({ lane: 'yellow', in_inbox: true, ...changes });
}

describe('the archive', () => {
	it('shows no lane and no progress on a card, but that the document is in the inbox', () => {
		const { container } = render(DocumentCard, { document: listed(), lookup: null });
		expect(container.querySelector('[data-lane]')).toBeNull();
		const mark = screen.getByRole('link', { name: m.in_inbox() });
		expect(mark.getAttribute('href')).toBe('/ui/inbox?tab=review');
		expect(screen.getByRole('link', { name: /Stromrechnung/ }).getAttribute('href')).toBe(
			'/ui/documents/doc-1'
		);
	});

	it('shows no progress of a document in processing', () => {
		render(DocumentCard, { document: listed({ lane: null }), lookup: null });
		expect(screen.queryByRole('progressbar')).toBeNull();
		expect(screen.getByRole('link', { name: m.in_inbox() }).getAttribute('href')).toBe(
			'/ui/inbox?tab=processing'
		);
	});

	it('says nothing of the inbox for a document that left it', () => {
		render(DocumentCard, { document: listed({ in_inbox: false, lane: 'green' }), lookup: null });
		expect(screen.queryByRole('link', { name: m.in_inbox() })).toBeNull();
	});

	it('shows no lane in a row, and what stands beside its link', () => {
		const aside = createRawSnippet(() => ({ render: () => '<button>beside</button>' }));
		const { container } = render(DocumentRow, {
			document: listed({ lane: null }),
			lookup: null,
			aside
		});
		expect(container.querySelector('[data-lane]')).toBeNull();
		expect(screen.queryByRole('progressbar')).toBeNull();
		const link = screen.getByRole('link', { name: /Stromrechnung/ });
		expect(within(link).queryByRole('button')).toBeNull();
		expect(screen.getByRole('button', { name: 'beside' })).toBeTruthy();
	});

	it.each([
		[null, 'processing'],
		['yellow', 'review'],
		['red', 'intervene'],
		['green', 'new']
	] as const)('leads a document with lane %s to the inbox tab %s', (lane, tab) => {
		render(InboxMark, { lane });
		expect(screen.getByRole('link', { name: m.in_inbox() }).getAttribute('href')).toBe(
			`/ui/inbox?tab=${tab}`
		);
	});
});
