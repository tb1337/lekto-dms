import { render, screen, waitFor } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import IconPicker from './IconPicker.svelte';

// The icon picker's panel is loaded when it opens; under a full parallel run that can take a
// while.
const LOADED = { timeout: 5000 };

describe('IconPicker', () => {
	it('offers the icons by area and takes one', async () => {
		const user = userEvent.setup();
		render(IconPicker, { id: 'icon', value: null });
		expect(screen.getByText(m.icon_none())).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.icon_choose() }));
		// The panel loads when the picker opens.
		expect(await screen.findByRole('region', { name: m.icon_area_money() }, LOADED)).toBeTruthy();
		expect(screen.getAllByRole('button', { pressed: false }).length).toBeGreaterThanOrEqual(170);
		await user.click(screen.getByTitle('piggy-bank'));
		expect(screen.getByText('piggy-bank')).toBeTruthy();
		// Closed again; the icon is drawn once it is loaded.
		expect(screen.queryByRole('region', { name: m.icon_area_money() })).toBeNull();
		await waitFor(() => expect(document.querySelector('svg.lucide-piggy-bank')).not.toBeNull());
	});

	it('searches every icon and removes the chosen one', async () => {
		const user = userEvent.setup();
		render(IconPicker, { id: 'icon', value: 'house' });
		await user.click(screen.getByRole('button', { name: m.icon_choose() }));
		await user.type(await screen.findByRole('searchbox', {}, LOADED), 'rocket');
		expect(screen.queryByRole('region')).toBeNull();
		expect(screen.getByTitle('rocket')).toBeTruthy();
		await user.clear(screen.getByRole('searchbox'));
		await user.type(screen.getByRole('searchbox'), 'zzzz');
		expect(screen.getByText(m.icon_search_none())).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.icon_done() }));
		await user.click(screen.getByRole('button', { name: m.icon_remove() }));
		expect(screen.getByText(m.icon_none())).toBeTruthy();
	});

	it('marks an unknown name with a stand-in', async () => {
		render(IconPicker, { id: 'icon', value: 'gone-icon' });
		await waitFor(() => expect(document.querySelector('[data-unknown-icon]')).not.toBeNull());
	});
});
