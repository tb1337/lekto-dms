import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import LayoutGrid from '@lucide/svelte/icons/layout-grid';
import List from '@lucide/svelte/icons/list';
import { describe, expect, it, vi } from 'vitest';
import Segmented from './Segmented.svelte';

const OPTIONS = [
	{ value: 'grid', label: 'Grid', icon: LayoutGrid },
	{ value: 'list', label: 'List', icon: List }
];

describe('Segmented', () => {
	it('presses the chosen one and reports a change once, not a click on the chosen one', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(Segmented, { label: 'Layout', value: 'grid', options: OPTIONS, onchange });
		const group = screen.getByRole('group', { name: 'Layout' });
		const grid = within(group).getByRole('button', { name: 'Grid' });
		const list = within(group).getByRole('button', { name: 'List' });
		expect([grid, list].map((button) => button.getAttribute('aria-pressed'))).toEqual([
			'true',
			'false'
		]);
		await user.click(grid);
		expect(onchange).not.toHaveBeenCalled();
		await user.click(list);
		expect(onchange).toHaveBeenCalledExactlyOnceWith('list');
		expect(list.getAttribute('aria-pressed')).toBe('true');
		expect(group.querySelector<HTMLElement>('[data-pill]')!.hidden).toBe(false);
	});

	it('holds an option that is not to be chosen now', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(Segmented, {
			label: 'Grouping',
			value: 'none',
			options: [
				{ value: 'none', label: 'None' },
				{ value: 'due', label: 'Deadline', disabled: true }
			],
			onchange
		});
		const due = screen.getByRole('button', { name: 'Deadline' });
		expect((due as HTMLButtonElement).disabled).toBe(true);
		await user.click(due);
		expect(onchange).not.toHaveBeenCalled();
	});

	it('names icons only by their label, read out and on hover', () => {
		render(Segmented, { label: 'Layout', value: 'list', options: OPTIONS, names: 'hidden' });
		const list = screen.getByRole('button', { name: 'List' });
		// On hover a tooltip says it (web/DESIGN.md: no native title on a button).
		expect(list.hasAttribute('title')).toBe(false);
		expect(
			list.getAttribute('data-tooltip-trigger') ?? list.getAttribute('data-state')
		).not.toBeNull();
		expect(list.textContent?.trim()).toBe('');
	});
});
