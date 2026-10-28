import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { choose, selectedValue } from '#lib/testing/select.ts';
import SearchSelect from './SearchSelect.svelte';

const OPTIONS = [
	{ value: 'c1', label: 'Stadtwerke', keywords: 'SWM Energie' },
	{ value: 'c2', label: 'Nord Versicherung' }
];

function field(props: Record<string, unknown> = {}) {
	const onchange = vi.fn();
	render(SearchSelect, {
		options: OPTIONS,
		title: 'Choose a contact',
		value: 'c2',
		placeholder: 'none yet',
		noneLabel: 'No contact',
		onchange,
		...props
	});
	return { onchange, trigger: screen.getByRole('combobox') };
}

afterEach(() => phone.override(null));

describe('SearchSelect', () => {
	it('opens as a sheet on a phone, named by its title, and closes on a choice', async () => {
		phone.override(true);
		const user = userEvent.setup();
		const { onchange, trigger } = field();
		expect(trigger.getAttribute('aria-haspopup')).toBe('dialog');
		await user.click(trigger);
		const sheet = await screen.findByRole('dialog', { name: 'Choose a contact' });
		await user.type(within(sheet).getByLabelText(m.assignment_search()), 'stadt');
		await user.click(within(sheet).getByRole('option', { name: 'Stadtwerke' }));
		expect(onchange).toHaveBeenLastCalledWith('c1');
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(trigger.textContent).toContain('Stadtwerke');
	});

	it('shows the chosen one, finds one by what it is also called, and clears', async () => {
		const user = userEvent.setup();
		const { onchange, trigger } = field();
		expect(trigger.textContent).toContain('Nord Versicherung');
		await fireEvent.click(trigger);
		await user.type(await screen.findByLabelText(m.assignment_search()), 'swm');
		// The popover is placed by measuring, which jsdom does not: it counts as hidden.
		const options = await screen.findAllByRole('option', { hidden: true });
		expect(options.map((option) => option.textContent?.trim())).toEqual(['Stadtwerke']);
		await user.click(options[0]);
		expect(onchange).toHaveBeenLastCalledWith('c1');
		expect(selectedValue(trigger)).toBe('c1');
		await choose(user, trigger, 'No contact');
		expect(onchange).toHaveBeenLastCalledWith('');
		expect(trigger.textContent).toContain('none yet');
	});

	it('says a value is set that the options do not hold, rather than none', () => {
		const { trigger } = field({ value: 'c9' });
		expect(trigger.textContent).toContain(m.rule_unknown());
		expect(trigger.textContent).not.toContain('none yet');
		expect(selectedValue(trigger)).toBe('c9');
	});

	it('opens without scrolling the page to the list before it is placed', async () => {
		const scroll = vi.spyOn(Element.prototype, 'scrollIntoView');
		const { trigger } = field();
		await fireEvent.click(trigger);
		await screen.findByLabelText(m.assignment_search());
		await new Promise((resolve) => setTimeout(resolve, 50));
		expect(scroll).not.toHaveBeenCalled();
		scroll.mockRestore();
	});

	it('makes what the search names after closing, once, and chooses it', async () => {
		const user = userEvent.setup();
		const create = vi.fn(async (name: string) => ({ value: 'c3', label: name }));
		const { onchange, trigger } = field({ create });
		await fireEvent.click(trigger);
		await user.type(await screen.findByLabelText(m.assignment_search()), 'Bäckerei Korn');
		const wanted = m.create_named({ name: 'Bäckerei Korn' });
		const offer = (await screen.findAllByRole('option', { hidden: true })).find(
			(option) => option.textContent?.trim() === wanted
		)!;
		await fireEvent.click(offer);
		await fireEvent.click(offer);
		await waitFor(() => expect(onchange).toHaveBeenLastCalledWith('c3'));
		expect(create).toHaveBeenCalledTimes(1);
		expect(create).toHaveBeenCalledWith('Bäckerei Korn');
		expect(trigger.textContent).toContain('Bäckerei Korn');
	});

	it('keeps the value when what was to be made was not', async () => {
		const user = userEvent.setup();
		const create = vi.fn(async () => null);
		const { onchange, trigger } = field({ create });
		await fireEvent.click(trigger);
		await user.type(await screen.findByLabelText(m.assignment_search()), 'Bäckerei Korn');
		await user.click(await screen.findByText(m.create_named({ name: 'Bäckerei Korn' })));
		await waitFor(() => expect(create).toHaveBeenCalledOnce());
		expect(onchange).not.toHaveBeenCalled();
		expect(selectedValue(trigger)).toBe('c2');
	});
});
