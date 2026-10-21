import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import InfoHint from './InfoHint.svelte';

describe('InfoHint', () => {
	it('shows the help only when asked, and keeps it for the field it describes', async () => {
		const user = userEvent.setup();
		render(InfoHint, {
			text: 'Die Dokumente gehören auch zu diesen Gruppen.',
			about: 'Gruppen',
			id: 'groups-hint'
		});
		const hidden = document.getElementById('groups-hint')!;
		expect(hidden.hidden).toBe(true);
		expect(hidden.textContent).toBe('Die Dokumente gehören auch zu diesen Gruppen.');
		const button = screen.getByRole('button', { name: m.hint_about({ name: 'Gruppen' }) });
		expect(button.getAttribute('type')).toBe('button');
		expect(screen.getAllByText('Die Dokumente gehören auch zu diesen Gruppen.')).toHaveLength(1);
		await user.click(button);
		expect(
			await screen.findAllByText('Die Dokumente gehören auch zu diesen Gruppen.', undefined, {
				timeout: 2000
			})
		).toHaveLength(2);
	});
});
