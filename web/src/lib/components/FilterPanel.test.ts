import { render, screen, within } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { monthPeriod, NO_FILTERS, yearPeriod, type Filters } from '#lib/filters.ts';
import type { Lookup, Tag } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import ActiveFilters from './ActiveFilters.svelte';
import FilterPanel from './FilterPanel.svelte';

function tag(id: string, path: string[], scope: string, color: string | null = null) {
	return { id, name: path[path.length - 1], path, scope, color, shown: true } as unknown as Tag;
}

const lookup = {
	contacts: ['Nord', 'Süd', 'Ost', 'West', 'Mitte', 'Hafen', 'Bahn', 'Post'].map((name) => ({
		id: name.toLowerCase(),
		name
	})),
	documentTypes: [{ id: 'k1', name: 'Rechnung' }],
	tags: [
		tag('t1', ['Steuer'], 'document', 'amber'),
		tag('t2', ['Steuer', 'Lohn'], 'document'),
		tag('g1', ['Versorger'], 'contact'),
		tag('p1', ['Wohnung'], 'topic')
	],
	fields: [],
	spaces: [],
	users: []
} as unknown as Lookup;

const facets: components['schemas']['DocumentFacetsOut'] = {
	total: 12,
	contacts: [
		{ id: 'nord', count: 5 },
		{ id: 'süd', count: 3 },
		{ id: null, count: 2 },
		...['ost', 'west', 'mitte', 'hafen', 'bahn'].map((id) => ({ id, count: 1 }))
	],
	document_types: [{ id: 'k1', count: 9 }],
	contact_groups: [],
	document_type_groups: [],
	topics: [{ id: 'p1', count: 2 }],
	tags: [
		{ id: 't1', count: 4 },
		{ id: 't2', count: 1 }
	],
	years: [
		{ year: 2026, count: 8, months: [{ month: '2026-09', count: 8 }] },
		{ year: 2025, count: 2, months: [{ month: '2025-12', count: 2 }] }
	],
	undated: 2
};

function panel(filters: Filters = NO_FILTERS, showCounts = true) {
	const onchange = vi.fn<(filters: Filters) => void>();
	render(FilterPanel, { filters, lookup, facets, showCounts, onchange });
	return onchange;
}

function group(name: string): HTMLElement {
	return screen.getByRole('region', { name });
}

describe('FilterPanel', () => {
	it('shows each value with its count, most first, and chooses one more of a group', async () => {
		const user = userEvent.setup();
		const onchange = panel({ ...NO_FILTERS, contacts: ['nord'] });
		const contacts = group(m.facet_contacts());
		const rows = within(contacts).getAllByRole('checkbox');
		expect(
			rows.map((row) => row.closest('label')?.textContent?.replace(/\s+/g, ' ').trim())
		).toEqual(['Nord 5', 'Süd 3', 'Ost 1', 'West 1', 'Mitte 1', 'Hafen 1']);
		expect((rows[0] as HTMLInputElement).checked).toBe(true);
		await user.click(within(contacts).getByLabelText(/Süd/));
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, contacts: ['nord', 'süd'] });
		// The rest behind "N more".
		await user.click(within(contacts).getByRole('button', { name: m.facet_more({ count: '1' }) }));
		expect(within(contacts).getByLabelText(/Bahn/)).toBeTruthy();
	});

	it('shows a tag by its own name with its colour, the path as tooltip', () => {
		panel();
		const tags = group(m.facet_tags());
		const lohn = within(tags).getByText('Lohn').closest('label')!;
		expect(lohn.getAttribute('title')).toBe('Steuer › Lohn');
		const steuer = within(tags).getByText('Steuer').closest('label')!;
		expect(steuer.querySelector('[aria-hidden="true"]')?.getAttribute('style')).toContain(
			'--tag-amber-foreground'
		);
	});

	it('keeps a chosen value that holds no documents, and shows no counts while searching', () => {
		panel({ ...NO_FILTERS, contacts: ['post'] }, false);
		const contacts = group(m.facet_contacts());
		expect((within(contacts).getByLabelText(/Post/) as HTMLInputElement).checked).toBe(true);
		expect(within(contacts).queryByText('5')).toBeNull();
	});

	it('chooses a year or a month, and lets it go on a second tap', async () => {
		const user = userEvent.setup();
		const onchange = panel();
		const period = group(m.facet_period());
		await user.click(within(period).getByRole('button', { name: /^2026/ }));
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, ...yearPeriod(2026) });
		await user.click(
			within(period).getByRole('button', { name: m.facet_months({ year: '2026' }) })
		);
		await user.click(within(period).getByRole('button', { name: /September/ }));
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, ...monthPeriod('2026-09') });
		expect(within(period).getByText(m.facet_undated({ count: '2' }))).toBeTruthy();
	});

	it('lets a chosen year go', async () => {
		const user = userEvent.setup();
		const onchange = panel({ ...NO_FILTERS, ...yearPeriod(2025) });
		const year = within(group(m.facet_period())).getByRole('button', { name: /^2025/ });
		expect(year.getAttribute('aria-pressed')).toBe('true');
		await user.click(year);
		expect(onchange).toHaveBeenLastCalledWith(NO_FILTERS);
	});
});

describe('ActiveFilters', () => {
	it('shows each chosen value as a chip that lets it go, and a reset', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn<(filters: Filters) => void>();
		const filters = {
			...NO_FILTERS,
			contacts: ['nord'],
			topics: ['p1'],
			...monthPeriod('2026-09')
		};
		render(ActiveFilters, { filters, lookup, onchange });
		await user.click(screen.getByRole('button', { name: m.filter_remove({ name: 'Nord' }) }));
		expect(onchange).toHaveBeenLastCalledWith({ ...filters, contacts: [] });
		const topic = screen.getByRole('button', { name: m.filter_topic_remove({ name: 'Wohnung' }) });
		expect(topic.closest('span')?.className).toContain('rounded-md');
		expect(screen.getByText(/September 2026/)).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.filter_reset() }));
		expect(onchange).toHaveBeenLastCalledWith(NO_FILTERS);
	});

	it('shows nothing while nothing is chosen, and no lane', () => {
		const { container } = render(ActiveFilters, { filters: NO_FILTERS, lookup, onchange: vi.fn() });
		expect(container.textContent?.trim()).toBe('');
		for (const label of [m.lane_green(), m.lane_yellow(), m.lane_red(), m.lane_running()]) {
			expect(screen.queryByRole('button', { name: label })).toBeNull();
		}
	});
});
