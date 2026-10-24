import { render, screen } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import type { FieldEvidence } from '#lib/document-view.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import FieldShell from './FieldShell.svelte';

const input = createRawSnippet(() => ({ render: () => '<input id="field-amount" />' }));
const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	fields: [],
	spaces: [],
	users: []
} as unknown as Lookup;

/** The evidence of a field whose quote stands on `pages`. */
function on(pages: number[]): FieldEvidence {
	const locations = pages.map((page) => ({
		page,
		boxes: [{ x: 0.1, y: 0.1, width: 0.2, height: 0.02 }]
	}));
	return { check: { field: 'field:amount', locations }, open: false } as unknown as FieldEvidence;
}

/** The page chips shown, of pages 1 to 20. */
const chips = () =>
	Array.from({ length: 20 }, (_, index) => index + 1).filter((page) =>
		screen.queryByRole('button', { name: m.source_jump({ page }) })
	);

describe('a field with the pages of its quote', () => {
	it('starts collapsed again when the field is read again on other pages', async () => {
		const user = userEvent.setup();
		const props = {
			key: 'field:amount',
			label: 'Betrag',
			inputId: 'field-amount',
			lookup,
			onfocus: () => {},
			onjump: () => {},
			children: input
		};
		const eight = [1, 2, 3, 4, 5, 6, 7, 8];
		const { rerender } = render(FieldShell, { ...props, evidence: on(eight) });
		expect(chips()).toHaveLength(6);
		await user.click(screen.getByRole('button', { name: m.source_more({ count: 2 }) }));
		expect(chips()).toHaveLength(8);
		// Loaded again with the same pages: it stays open.
		await rerender({ ...props, evidence: on(eight) });
		expect(chips()).toHaveLength(8);
		// Read again, now on other pages: collapsed, with the rest behind "+N".
		await rerender({ ...props, evidence: on([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]) });
		expect(chips()).toHaveLength(6);
		expect(screen.getByRole('button', { name: m.source_more({ count: 6 }) })).toBeTruthy();
	});
});
