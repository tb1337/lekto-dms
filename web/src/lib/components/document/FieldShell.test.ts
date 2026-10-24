import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
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

describe('the mark of a field', () => {
	const props = {
		key: 'field:amount',
		label: 'Betrag',
		inputId: 'field-amount',
		lookup,
		onjump: () => {}
	};

	it('stays while the field holds the focus, and goes once the focus leaves it', async () => {
		const onfocus = vi.fn();
		render(FieldShell, { ...props, onfocus, children: input });
		const field = screen.getByRole('textbox');
		const shell = screen.getByRole('group');
		field.focus();
		expect(onfocus).toHaveBeenLastCalledWith('field:amount');
		onfocus.mockClear();
		await fireEvent.mouseLeave(shell);
		expect(onfocus).not.toHaveBeenCalled();
		field.blur();
		await waitFor(() => expect(onfocus).toHaveBeenLastCalledWith(null));
	});

	it('stays while a list the field opened holds the focus', async () => {
		const onfocus = vi.fn();
		const trigger = createRawSnippet(() => ({
			render: () => '<button id="field-amount" aria-expanded="true">Open</button>'
		}));
		render(FieldShell, { ...props, onfocus, children: trigger });
		const outside = window.document.createElement('button');
		window.document.body.append(outside);
		const button = screen.getByRole('button', { name: 'Betrag' });
		button.focus();
		onfocus.mockClear();
		// The popover stands outside the field in the page and takes the focus.
		outside.focus();
		await new Promise((resolve) => setTimeout(resolve, 10));
		expect(onfocus).not.toHaveBeenCalled();
		await fireEvent.mouseLeave(screen.getByRole('group'));
		expect(onfocus).not.toHaveBeenCalled();
		// Closed: the focus is elsewhere, the mark goes.
		button.setAttribute('aria-expanded', 'false');
		await fireEvent.mouseLeave(screen.getByRole('group'));
		expect(onfocus).toHaveBeenLastCalledWith(null);
		outside.remove();
	});
});
