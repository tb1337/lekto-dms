import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import SecretDialog from './SecretDialog.svelte';

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('SecretDialog', () => {
	it('says a secret was copied until another one is shown', async () => {
		const user = userEvent.setup();
		const writeText = vi.fn(async () => {});
		vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
		const { rerender } = render(SecretDialog, {
			secret: 'first',
			title: 'Token',
			description: 'Once',
			onclose: () => {}
		});
		await user.click(await screen.findByRole('button', { name: m.secret_copy() }));
		expect(writeText).toHaveBeenCalledWith('first');
		expect(screen.getByRole('button', { name: m.secret_copied() })).toBeTruthy();
		await rerender({ secret: 'second' });
		expect(screen.getByRole('button', { name: m.secret_copy() })).toBeTruthy();
	});
});
