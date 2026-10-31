import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import BeamTitle from './BeamTitle.svelte';

describe('the title that shows a document in the Beam', () => {
	it('is one button, the eye before the title, and opens nothing directly', async () => {
		const onview = vi.fn();
		render(BeamTitle, { title: 'Kontoauszug Juli 2026', onview });
		const button = screen.getByRole('button', {
			name: m.beam_open_named({ title: 'Kontoauszug Juli 2026' })
		});
		expect(button.firstElementChild?.tagName.toLowerCase()).toBe('svg');
		expect(button.textContent?.trim()).toBe('Kontoauszug Juli 2026');
		expect(button.className).toContain('text-brand');
		expect(screen.queryByRole('link')).toBeNull();
		await userEvent.click(button);
		expect(onview).toHaveBeenCalledOnce();
	});

	it('names a value by what it says, in mono', () => {
		render(BeamTitle, {
			title: 'DE02 1203',
			label: 'DE02 1203 ansehen',
			mono: true,
			onview: vi.fn()
		});
		const button = screen.getByRole('button', { name: 'DE02 1203 ansehen' });
		expect(button.querySelector('.font-mono')?.textContent).toBe('DE02 1203');
	});
});
