import { fireEvent, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { sortLabel, sortShort } from '#lib/listing.ts';
import { m } from '#lib/paraglide/messages.js';
import SortMenu from './SortMenu.svelte';

const OPTIONS = (['-document_date', 'document_date', 'title'] as const).map((value) => ({
	value,
	label: sortLabel(value)
}));

describe('SortMenu', () => {
	it('says by what and which way it sorts, and lists every sort to choose', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(SortMenu, {
			options: OPTIONS,
			value: '-document_date',
			short: sortShort('-document_date'),
			onchange
		});
		const face = screen.getByRole('button', {
			name: m.sort_current({ label: sortLabel('-document_date') })
		});
		expect(face.textContent).toContain(m.sort_short_document_date());
		await fireEvent.pointerDown(face, { button: 0, pointerType: 'mouse' });
		await user.click(await screen.findByRole('menuitemradio', { name: sortLabel('title') }));
		expect(onchange).toHaveBeenCalledWith('title');
	});

	it('names a field it sorts by, and nothing goes up or down by relevance', () => {
		expect(sortShort('-field', { name: 'Fällig am' })).toEqual({
			key: 'Fällig am',
			direction: 'down'
		});
		expect(sortShort('relevance').direction).toBeNull();
	});
});
