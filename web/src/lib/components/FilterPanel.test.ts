import { render, screen, within } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { monthPeriod, NO_FILTERS, yearPeriod, type Filters } from '#lib/filters.ts';
import { formatDate } from '#lib/i18n.ts';
import type { Lookup, Tag } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import ActiveFilters from './ActiveFilters.svelte';
import FilterPanel from './FilterPanel.svelte';
import PeriodFacet from './PeriodFacet.svelte';

type Facets = components['schemas']['DocumentFacetsOut'];

function tag(
	id: string,
	path: string[],
	scope: string,
	color: string | null = null,
	parent: string | null = null
) {
	return {
		id,
		name: path[path.length - 1],
		path,
		scope,
		color,
		parent_id: parent,
		shown: true
	} as unknown as Tag;
}

const lookup = {
	contacts: ['Nord', 'Süd', 'Ost', 'West', 'Mitte', 'Hafen', 'Bahn', 'Post'].map((name) => ({
		id: name.toLowerCase(),
		name,
		group_ids: name === 'Nord' ? ['g1'] : name === 'Süd' ? ['g1a'] : []
	})),
	documentTypes: [
		{ id: 'k1', name: 'Rechnung', group_ids: ['g2'] },
		{ id: 'k2', name: 'Brief', group_ids: [] }
	],
	tags: [
		tag('t1', ['Steuer'], 'document', 'amber'),
		tag('t2', ['Steuer', 'Lohn'], 'document', null, 't1'),
		tag('g1', ['Versorger'], 'contact', 'blue'),
		tag('g1a', ['Versorger', 'Wasser'], 'contact', null, 'g1'),
		tag('g2', ['Finanzen'], 'document_type'),
		tag('p1', ['Wohnung'], 'topic')
	],
	fields: [],
	spaces: [],
	users: []
} as unknown as Lookup;

const facets: Facets = {
	total: 12,
	contacts: [
		{ id: 'nord', count: 5 },
		{ id: 'süd', count: 3 },
		{ id: null, count: 2 },
		...['ost', 'west', 'mitte', 'hafen', 'bahn'].map((id) => ({ id, count: 1 }))
	],
	document_types: [{ id: 'k1', count: 9 }],
	contact_groups: [
		{ id: 'g1', count: 8 },
		{ id: 'g1a', count: 3 }
	],
	document_type_groups: [{ id: 'g2', count: 9 }],
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

/** A section of the panel by its title (its summary follows the title in its name). */
function section(title: string): HTMLElement {
	return screen.getByRole('region', { name: new RegExp(`^${title}`) });
}

/** The name of a month of 2026 (`index` from 0) as its bar says it, with its count. */
function monthName(index: number): RegExp {
	return new RegExp(`^${formatDate(new Date(2026, index, 1), { month: 'long', year: 'numeric' })}`);
}

function rows(within_: HTMLElement): string[] {
	return within(within_)
		.getAllByRole('checkbox')
		.map((row) => row.closest('label')?.textContent?.replace(/\s+/g, ' ').trim() ?? '');
}

describe('FilterPanel', () => {
	it('shows the most frequent contacts, most first, with the chosen ones, and chooses more', async () => {
		const user = userEvent.setup();
		const onchange = panel({ ...NO_FILTERS, contacts: ['nord'] });
		const contacts = section(m.facet_contact());
		expect(rows(contacts)).toEqual(['Nord 5', 'Süd 3', 'Bahn 1', 'Hafen 1', 'Mitte 1']);
		expect((within(contacts).getByLabelText(/Nord/) as HTMLInputElement).checked).toBe(true);
		await user.click(within(contacts).getByLabelText(/Süd/));
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, contacts: ['nord', 'süd'] });
		// A search finds one beyond them.
		await user.type(within(contacts).getByLabelText(m.facet_search_contacts()), 'po');
		expect(rows(contacts)).toEqual(['Post 0']);
	});

	it('shows every contact in a picker, by letter, with its groups', async () => {
		const user = userEvent.setup();
		const onchange = panel();
		await user.click(
			within(section(m.facet_contact())).getByRole('button', {
				name: m.facet_all_contacts({ count: '8' })
			})
		);
		const picker = await screen.findByRole('dialog', { name: m.facet_contacts() });
		expect(within(picker).getByText('Versorger')).toBeTruthy();
		await user.click(within(picker).getByLabelText(/Post/));
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, contacts: ['post'] });
	});

	it('shows the contact groups before the contacts, and narrows the contacts to a chosen one', async () => {
		const user = userEvent.setup();
		const onchange = panel();
		const contacts = section(m.facet_contact());
		const groups = within(contacts).getByRole('group', { name: m.facet_contact_groups() });
		const list = within(contacts).getByRole('group', { name: m.facet_top_contacts() });
		expect(groups.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		// A group as its chip: outlined in its colour.
		const versorger = within(groups).getByRole('button', { name: /^Versorger/ });
		expect(versorger.getAttribute('style')).toContain('--tag-blue-foreground');
		expect(versorger.className).toContain('border-(--chip-fg)/45');
		await user.click(versorger);
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, contactGroups: ['g1'] });
	});

	it('lists the contacts of a chosen group and of the groups below it', () => {
		panel({ ...NO_FILTERS, contactGroups: ['g1'] });
		const contacts = section(m.facet_contact());
		const list = within(contacts).getByRole('group', {
			name: m.facet_contacts_in({ groups: 'Versorger' })
		});
		expect(rows(list)).toEqual(['Nord 5', 'Süd 3']);
		const versorger = within(contacts).getByRole('button', { name: /^Versorger/ });
		expect(versorger.getAttribute('aria-pressed')).toBe('true');
		// The section says what is chosen in it.
		expect(contacts.getAttribute('aria-labelledby')).toBeTruthy();
		expect(within(contacts).getByRole('button', { expanded: true }).textContent).toContain(
			'Versorger'
		);
	});

	it('keeps the type section closed until it is opened, unless a type is chosen', async () => {
		const user = userEvent.setup();
		panel();
		const types = section(m.facet_type());
		const header = within(types).getByRole('button', { expanded: false });
		expect(within(types).queryByRole('checkbox')).toBeNull();
		await user.click(header);
		expect(rows(types)).toEqual(['Rechnung 9']);
	});

	it('shows the tags as their chips in their colours, the path as tooltip', async () => {
		const user = userEvent.setup();
		const onchange = panel({ ...NO_FILTERS, tags: ['t2'] });
		const tags = section(m.facet_tags());
		const steuer = within(tags).getByRole('button', { name: /^Steuer/ });
		expect(steuer.getAttribute('style')).toContain('--tag-amber-foreground');
		expect(steuer.getAttribute('aria-pressed')).toBe('false');
		const lohn = within(tags).getByRole('button', { name: /^Lohn/ });
		expect(lohn.getAttribute('title')).toBe('Steuer › Lohn');
		expect(lohn.getAttribute('aria-pressed')).toBe('true');
		await user.click(steuer);
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, tags: ['t2', 't1'] });
	});

	it('keeps a chosen value that holds no documents, and shows no counts while searching', () => {
		panel({ ...NO_FILTERS, contacts: ['post'] }, false);
		const contacts = section(m.facet_contact());
		expect((within(contacts).getByLabelText(/Post/) as HTMLInputElement).checked).toBe(true);
		expect(within(contacts).queryByText('5')).toBeNull();
	});

	it('shows no counts while none are known', () => {
		const onchange = vi.fn<(filters: Filters) => void>();
		render(FilterPanel, { filters: NO_FILTERS, lookup, facets: null, showCounts: true, onchange });
		const groups = within(section(m.facet_contact())).getByRole('group', {
			name: m.facet_contact_groups()
		});
		expect(within(groups).getByRole('button', { name: 'Versorger' })).toBeTruthy();
		expect(within(section(m.facet_tags())).getByRole('button', { name: 'Steuer' })).toBeTruthy();
	});

	it('chooses a year, a quick period, or a month of the chosen year', async () => {
		const user = userEvent.setup();
		const onchange = panel();
		const period = section(m.facet_period());
		await user.click(within(period).getByRole('button', { name: /^2026/ }));
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, ...yearPeriod(2026) });
		await user.click(within(period).getByRole('button', { name: m.facet_this_year() }));
		expect(onchange).toHaveBeenLastCalledWith({
			...NO_FILTERS,
			...yearPeriod(new Date().getFullYear())
		});
		expect(within(period).getByText(m.facet_undated({ count: '2' }))).toBeTruthy();
		// No months until a year is chosen.
		expect(within(period).queryByRole('group')).toBeNull();
	});

	it('shows the months of a chosen year, those without documents disabled', async () => {
		const user = userEvent.setup();
		const onchange = panel({ ...NO_FILTERS, ...yearPeriod(2026) });
		const months = within(section(m.facet_period())).getByRole('group', {
			name: m.facet_months({ year: '2026' })
		});
		const october = within(months).getByRole('button', { name: monthName(9) });
		expect((october as HTMLButtonElement).disabled).toBe(true);
		await user.click(within(months).getByRole('button', { name: monthName(8) }));
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, ...monthPeriod('2026-09') });
	});

	it('goes back to the year from a chosen month', async () => {
		const user = userEvent.setup();
		const onchange = panel({ ...NO_FILTERS, ...monthPeriod('2026-09') });
		const months = within(section(m.facet_period())).getByRole('group', {
			name: m.facet_months({ year: '2026' })
		});
		const september = within(months).getByRole('button', { name: monthName(8) });
		expect(september.getAttribute('aria-pressed')).toBe('true');
		await user.click(september);
		expect(onchange).toHaveBeenLastCalledWith({ ...NO_FILTERS, ...yearPeriod(2026) });
	});

	it('lets a chosen year go', async () => {
		const user = userEvent.setup();
		const onchange = panel({ ...NO_FILTERS, ...yearPeriod(2025) });
		const year = within(section(m.facet_period())).getByRole('button', { name: /^2025/ });
		expect(year.getAttribute('aria-pressed')).toBe('true');
		await user.click(year);
		expect(onchange).toHaveBeenLastCalledWith(NO_FILTERS);
	});
});

describe('PeriodFacet', () => {
	it('keeps the older years behind one tile, but not a single one', async () => {
		const user = userEvent.setup();
		const years = (count: number) =>
			Array.from({ length: count }, (_, index) => ({ year: 2026 - index, count: 1, months: [] }));
		const props = {
			undated: 0,
			period: { dateFrom: null, dateTo: null },
			showCounts: true,
			onchange: vi.fn()
		};
		const { unmount } = render(PeriodFacet, { ...props, years: years(10) });
		expect(screen.getByRole('button', { name: /^2017/ })).toBeTruthy();
		unmount();
		render(PeriodFacet, { ...props, years: years(12) });
		expect(screen.queryByRole('button', { name: /^2017/ })).toBeNull();
		await user.click(
			screen.getByRole('button', { name: `${m.facet_older({ from: '2015', to: '2017' })} 3` })
		);
		expect(screen.getByRole('button', { name: /^2015/ })).toBeTruthy();
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
		// A pill like every chip (web/DESIGN.md), the topic with an edge.
		expect(topic.closest('span')?.className).toContain('rounded-full');
		expect(topic.closest('span')?.className).toMatch(/(^| )border( |$)/);
		expect(screen.getByText(/September 2026/)).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.filter_reset() }));
		expect(onchange).toHaveBeenLastCalledWith(NO_FILTERS);
	});

	it('shows tags, topics and groups as their chips, in their colours', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn<(filters: Filters) => void>();
		const filters = { ...NO_FILTERS, tags: ['t1'], contactGroups: ['g1'] };
		render(ActiveFilters, { filters, lookup, onchange });
		const remove = screen.getByRole('button', { name: m.filter_tag_remove({ name: 'Steuer' }) });
		expect(remove.closest('span')?.getAttribute('style')).toContain('--tag-amber-foreground');
		const group = screen.getByRole('button', {
			name: m.filter_group_remove({ name: 'Versorger' })
		});
		expect(group.closest('span')?.className).toContain('border-(--chip-fg)/45');
		await user.click(remove);
		expect(onchange).toHaveBeenLastCalledWith({ ...filters, tags: [] });
	});

	it('shows nothing while nothing is chosen, and no lane', () => {
		const { container } = render(ActiveFilters, { filters: NO_FILTERS, lookup, onchange: vi.fn() });
		expect(container.textContent?.trim()).toBe('');
		for (const label of [m.lane_green(), m.lane_yellow(), m.lane_red(), m.lane_running()]) {
			expect(screen.queryByRole('button', { name: label })).toBeNull();
		}
	});
});
