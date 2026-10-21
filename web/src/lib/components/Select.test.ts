import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { phone } from '#lib/phone.svelte.ts';
import { choose, optionsOf, selectedValue } from '#lib/testing/select.ts';
import Select from './Select.svelte';

const OPTIONS = [
	{ value: '', label: 'None' },
	{ value: 'a', label: 'Alpha' },
	{ value: 'b', label: 'Beta' }
];

afterEach(() => phone.override(null));

describe('Select', () => {
	it('is a list wider than a phone: its value shows, a choice is reported', async () => {
		const onchange = vi.fn();
		render(Select, { options: OPTIONS, value: 'a', 'aria-label': 'Pick', onchange });
		const field = screen.getByRole('combobox', { name: 'Pick' });
		expect(field.tagName).toBe('BUTTON');
		expect(field.textContent).toContain('Alpha');
		expect((await optionsOf(field)).map((option) => option.label)).toEqual([
			'None',
			'Alpha',
			'Beta'
		]);
		await choose(userEvent.setup(), field, 'b');
		expect(onchange).toHaveBeenCalledWith('b');
		expect(selectedValue(field)).toBe('b');
		expect(field.textContent).toContain('Beta');
	});

	it('is the system’s own on a phone', async () => {
		phone.override(true);
		const onchange = vi.fn();
		render(Select, { options: OPTIONS, value: '', 'aria-label': 'Pick', onchange });
		const field = screen.getByRole('combobox', { name: 'Pick' });
		expect(field.tagName).toBe('SELECT');
		await choose(userEvent.setup(), field, 'a');
		expect(onchange).toHaveBeenCalledWith('a');
	});
});
