import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import BetaPill from './BetaPill.svelte';

describe('BetaPill', () => {
	it('is a small word at a menu entry', () => {
		render(BetaPill);
		const pill = screen.getByText(m.beta());
		expect(pill.tagName).toBe('SPAN');
		expect(pill.className).toContain('bg-beta');
		expect(screen.queryByRole('button')).toBeNull();
	});

	it('is an info tip beside a title, with the note', async () => {
		const user = userEvent.setup();
		render(BetaPill, { tip: 'Neu: kann danebenliegen.' });
		const button = screen.getByRole('button', { name: m.beta_about() });
		expect(button.textContent?.trim()).toBe(m.beta());
		expect(button.className).toContain('bg-beta');
		await user.click(button);
		expect(await screen.findByText('Neu: kann danebenliegen.')).toBeTruthy();
		expect(button.dataset.open).toBe('true');
	});
});
