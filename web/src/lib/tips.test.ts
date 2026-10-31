import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { createRawSnippet } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import IconButton from '#lib/components/IconButton.svelte';
import InfoTip from '#lib/components/InfoTip.svelte';

const icon = createRawSnippet(() => ({ render: () => '<svg aria-hidden="true"></svg>' }));
const text = createRawSnippet(() => ({ render: () => '<p>Was die Herkunft heißt</p>' }));

/** The boxes of help on the page, by their text. */
function boxes(): string[] {
	return [...document.querySelectorAll('[data-slot="tooltip-content"], [data-info-tip]')].map(
		(box) => box.textContent?.trim() ?? ''
	);
}

afterEach(() => {
	document.body.innerHTML = '';
});

describe('the boxes of help (web/DESIGN.md, "Help and tooltips")', () => {
	it('shows one at a time: the next closes the one before at once, without its delay', async () => {
		const user = userEvent.setup();
		render(IconButton, { label: 'Bearbeiten', children: icon });
		render(IconButton, { label: 'Löschen', children: icon });
		await user.hover(screen.getByRole('button', { name: 'Bearbeiten' }));
		await waitFor(() => expect(boxes()).toEqual(['Bearbeiten']));
		await user.hover(screen.getByRole('button', { name: 'Löschen' }));
		// At once: no delay while one shows, and the one before is gone in the same moment.
		expect(boxes()).toEqual(['Löschen']);
	});

	it('closes a tooltip when an info tip opens, and the info tip when a tooltip opens', async () => {
		const user = userEvent.setup();
		render(IconButton, { label: 'Bearbeiten', children: icon });
		render(InfoTip, { label: 'Hinweis zu Herkunft', children: text });
		await user.hover(screen.getByRole('button', { name: 'Bearbeiten' }));
		await waitFor(() => expect(boxes()).toEqual(['Bearbeiten']));
		await user.hover(screen.getByRole('button', { name: 'Hinweis zu Herkunft' }));
		await waitFor(() => expect(boxes()).toEqual(['Was die Herkunft heißt']));
		await user.hover(screen.getByRole('button', { name: 'Bearbeiten' }));
		await waitFor(() => expect(boxes()).toEqual(['Bearbeiten']));
	});

	it('opens none under a pointer resting where it clicked, but once it moved', async () => {
		const user = userEvent.setup();
		render(IconButton, { label: 'Bearbeiten', children: icon });
		const button = screen.getByRole('button', { name: 'Bearbeiten' });
		await user.pointer({ keys: '[MouseLeft]', target: button, coords: { x: 10, y: 10 } });
		// What a dialog leaves when it closes beneath the resting pointer: it enters the button.
		await user.unhover(button);
		await user.pointer({ target: button, coords: { x: 10, y: 10 } });
		await new Promise((resolve) => setTimeout(resolve, 400));
		expect(boxes()).toEqual([]);
		await user.pointer({ target: document.body, coords: { x: 200, y: 200 } });
		await user.pointer({ target: button, coords: { x: 12, y: 12 } });
		await waitFor(() => expect(boxes()).toEqual(['Bearbeiten']));
	});

	it('opens a tooltip on a focus Tab brings, not on one a dialog hands back', async () => {
		const user = userEvent.setup();
		render(IconButton, { label: 'Bearbeiten', children: icon });
		const button = screen.getByRole('button', { name: 'Bearbeiten' });
		// What a dialog does when it closes: the focus back to the button that opened it.
		button.focus();
		await new Promise((resolve) => setTimeout(resolve, 400));
		expect(boxes()).toEqual([]);
		button.blur();
		await user.tab();
		expect(document.activeElement).toBe(button);
		await waitFor(() => expect(boxes()).toEqual(['Bearbeiten']));
	});
});
