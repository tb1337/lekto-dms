import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import InfoTip from './InfoTip.svelte';

const text = createRawSnippet(() => ({ render: () => '<p>Eingabe 3.923 Token</p>' }));

describe('InfoTip', () => {
	it('opens its box in a layer over the page, not inside its column, and closes it again', async () => {
		const user = userEvent.setup();
		const { container } = render(InfoTip, { label: 'Token', id: 'tip', children: text });
		const button = screen.getByRole('button', { name: 'Token' });
		expect(button.getAttribute('aria-expanded')).toBe('false');
		await user.click(button);
		const box = await screen.findByText('Eingabe 3.923 Token');
		expect(button.getAttribute('aria-expanded')).toBe('true');
		expect(container.contains(box)).toBe(false);
		expect(box.closest('[data-info-tip]')?.id).toBe('tip');
		await user.click(button);
		expect(button.getAttribute('aria-expanded')).toBe('false');
	});
});
