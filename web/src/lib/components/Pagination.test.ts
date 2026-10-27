// The pages of a table: which items show, the page before and after, the numbers near by.
import { fireEvent, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import Pagination from './Pagination.svelte';

afterEach(() => localStorage.clear());

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

	it('offers the page sizes of a table and remembers the choice for it', async () => {
		const onsize = vi.fn();
		render(Pagination, {
			page: 1,
			total: 1284,
			size: 50,
			table: 'jobs',
			onchange: vi.fn(),
			onsize
		});
		await fireEvent.pointerDown(
			screen.getByRole('button', { name: m.pagination_size({ size: '50' }) }),
			{ button: 0, pointerType: 'mouse' }
		);
		await screen.findByRole('menuitemradio', { name: m.pagination_size({ size: '25' }) });
		const sizes = screen.getAllByRole('menuitemradio');
		expect(sizes.map((item) => item.textContent?.trim())).toEqual(
			['25', '50', '100'].map((size) => m.pagination_size({ size }))
		);
		await userEvent.click(
			screen.getByRole('menuitemradio', { name: m.pagination_size({ size: '100' }) })
		);
		expect(onsize.mock.calls).toEqual([[100]]);
		expect(localStorage.getItem('lekto.page-size.jobs')).toBe('100');
	});

	it('offers no size while all items fit on the smallest page, nor without a table', () => {
		render(Pagination, { page: 1, total: 20, size: 50, table: 'jobs', onchange: vi.fn() });
		render(Pagination, { page: 1, total: 1284, size: 50, onchange: vi.fn() });
		expect(screen.queryByRole('button', { name: m.pagination_size({ size: '50' }) })).toBeNull();
	});
});
