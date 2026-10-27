import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { formatDate } from '#lib/i18n.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
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
		// To the document, as opened from the inbox.
		const mark = screen.getByRole('link', { name: m.in_inbox() });
		expect(mark.getAttribute('href')).toBe('/ui/documents/doc-1?from=inbox');
		// A badge on the card's corner: beside the card, which cuts off what overflows it.
		const card = screen.getByRole('link', { name: /Stromrechnung/ }).parentElement!;
		expect(card.contains(mark)).toBe(false);
		expect(card.parentElement!.contains(mark)).toBe(true);
		expect(screen.getByRole('link', { name: /Stromrechnung/ }).getAttribute('href')).toBe(
			'/ui/documents/doc-1'
		);
	});

	it('shows no progress of a document in processing', () => {
		render(DocumentCard, { document: listed({ lane: null }), lookup: null });
		expect(screen.queryByRole('progressbar')).toBeNull();
		expect(screen.getByRole('link', { name: m.in_inbox() }).getAttribute('href')).toBe(
			'/ui/documents/doc-1?from=inbox'
		);
	});

	it('says nothing of the inbox for a document that left it', () => {
		render(DocumentCard, { document: listed({ in_inbox: false, lane: 'green' }), lookup: null });
		expect(screen.queryByRole('link', { name: m.in_inbox() })).toBeNull();
	});

	it('shows the contact in the head, the chips on the first page, then title, type and date', () => {
		const lookup = {
			contacts: [{ id: 'c1', name: 'Stadtwerke Süd', group_ids: ['g1'] }],
			documentTypes: [{ id: 'k1', name: 'Rechnung', group_ids: [], icon: 'receipt' }],
			tags: [
				{ id: 't1', name: 'zu bezahlen', path: ['zu bezahlen'], scope: 'document', shown: true },
				{ id: 'g1', name: 'Versorger', path: ['Versorger'], scope: 'contact', shown: true }
			],
			fields: [],
			spaces: [],
			users: []
		} as unknown as Lookup;
		const { container } = render(DocumentCard, {
			document: listed({
				contact_id: 'c1',
				document_type_id: 'k1',
				tag_ids: ['t1'],
				document_date: '2026-10-01',
				page_count: 2
			}),
			lookup
		});
		const link = screen.getByRole('link', { name: /Stromrechnung/ });
		const [head, page, text] = [...link.children];
		expect(within(head as HTMLElement).getByText('Stadtwerke Süd')).toBeTruthy();
		expect(head.getAttribute('title')).toBe('Stadtwerke Süd');
		// Only the page count stands on the page, as glass; the tag and the contact's group stand
		// below the title (web/DESIGN.md, "Document card").
		const count = within(page as HTMLElement).getByText(m.doc_pages_short({ count: 2 }));
		expect(count.classList.contains('mark-glass')).toBe(true);
		expect(within(page as HTMLElement).queryByText('zu bezahlen')).toBeNull();
		expect(within(text as HTMLElement).getByText('zu bezahlen')).toBeTruthy();
		expect(within(text as HTMLElement).getByText('Versorger')).toBeTruthy();
		expect(text.textContent).toContain('Stromrechnung');
		expect(text.textContent).toContain('Rechnung');
		expect(text.textContent).toContain(formatDate('2026-10-01'));
		expect(container.querySelector('[data-lane]')).toBeNull();
	});

	it('keeps the head without a contact, so that the first pages stand level', () => {
		render(DocumentCard, { document: listed({ contact_id: null }), lookup: null });
		const link = screen.getByRole('link', { name: /Stromrechnung/ });
		expect(link.children[0].textContent?.trim()).toBe(m.doc_no_contact());
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

	it('leads to the document as opened from the inbox', () => {
		render(InboxMark, { id: 'doc-7' });
		expect(screen.getByRole('link', { name: m.in_inbox() }).getAttribute('href')).toBe(
			'/ui/documents/doc-7?from=inbox'
		);
	});
});
