import { render, screen, waitFor, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import TabBar from './TabBar.svelte';

const TABS = [
	{ key: '', href: '/ui/inbox', label: 'All', count: 3 },
	{ key: 'new', href: '/ui/inbox?tab=new', label: 'New', count: 0 },
	{ key: 'log', href: '/ui/inbox?tab=log', label: 'Log', marker: 'needs a look' }
];

function bar(current: string) {
	const view = render(TabBar, { label: 'Tabs', tabs: TABS, current });
	const nav = screen.getByRole('navigation', { name: 'Tabs' });
	const pill = nav.querySelector<HTMLElement>('[data-pill]')!;
	return { ...view, nav, pill };
}

describe('TabBar', () => {
	it('marks the current tab, with its count, a count of 0 left out, and a marker read out', () => {
		const { nav } = bar('');
		const links = within(nav).getAllByRole('link');
		expect(links.map((link) => link.getAttribute('aria-current'))).toEqual(['page', null, null]);
		expect(links[0].textContent).toContain('3');
		expect(links[1].textContent?.trim()).toBe('New');
		expect(within(links[2]).getByText('needs a look').className).toContain('sr-only');
	});

	it('lays the pill under the current tab, moving only after its first placing', async () => {
		const { nav, pill, rerender } = bar('new');
		expect(pill.hidden).toBe(false);
		expect(pill.getAttribute('aria-hidden')).toBe('true');
		await waitFor(() => expect(pill.dataset.moving).toBe(''));
		await rerender({ current: 'log' });
		expect(within(nav).getByRole('link', { name: /Log/ }).getAttribute('aria-current')).toBe(
			'page'
		);
		expect(pill.hidden).toBe(false);
	});

	it('hides the pill when no tab is current', () => {
		const { pill } = bar('none');
		expect(pill.hidden).toBe(true);
	});
});
