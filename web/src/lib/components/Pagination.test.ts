// The pages of a table: which items show, the page before and after, the numbers near by.
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import Pagination from './Pagination.svelte';

describe('the pagination', () => {
	it('says which items show and turns the pages', async () => {
		const onchange = vi.fn();
		render(Pagination, { page: 10, total: 1284, size: 50, onchange });
		expect(screen.getByText(/451 – 500 (von|of) 1[.,]284/)).toBeTruthy();
		const buttons = screen.getAllByRole('button').map((button) => button.textContent?.trim());
		expect(buttons).toEqual(['', '1', '9', '10', '11', '26', '']);
		expect(screen.getByRole('button', { name: m.pagination_page({ page: '10' }) })).toHaveProperty(
			'ariaCurrent',
			'page'
		);
		await userEvent.click(screen.getByRole('button', { name: m.pagination_next() }));
		await userEvent.click(screen.getByRole('button', { name: m.pagination_page({ page: '26' }) }));
		await userEvent.click(screen.getByRole('button', { name: m.pagination_page({ page: '10' }) }));
		expect(onchange.mock.calls).toEqual([[11], [26]]);
	});

	it('shows only the count on a single page', () => {
		render(Pagination, { page: 1, total: 6, size: 50, onchange: vi.fn() });
		expect(screen.getByText(/1 – 6 (von|of) 6/)).toBeTruthy();
		expect(screen.queryByRole('button')).toBeNull();
		render(Pagination, { page: 1, total: 0, size: 50, onchange: vi.fn() });
		expect(screen.getByText(/0 – 0 (von|of) 0/)).toBeTruthy();
	});
});
