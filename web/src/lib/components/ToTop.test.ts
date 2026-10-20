import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import ToTop from './ToTop.svelte';

async function scrollTo(y: number) {
	Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
	await fireEvent.scroll(window);
}

afterEach(async () => {
	await scrollTo(0);
	vi.restoreAllMocks();
});

describe('ToTop', () => {
	it('comes once more than a screen lies above, with the page one stands on', async () => {
		render(ToTop, { current: 7, total: 23 });
		expect(screen.queryByRole('button')).toBeNull();
		await scrollTo(window.innerHeight + 1);
		const up = screen.getByRole('button', { name: m.to_top_page({ current: 7, total: 23 }) });
		expect(up.textContent?.trim()).toBe(m.to_top_count({ current: 7, total: 23 }));
		const scrolled = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
		await fireEvent.click(up);
		expect(scrolled).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
	});

	it('shows only the arrow without pages to count', async () => {
		render(ToTop, { current: 1, total: 1 });
		await scrollTo(window.innerHeight * 3);
		const up = screen.getByRole('button', { name: m.to_top() });
		expect(up.textContent?.trim()).toBe('');
	});
});
