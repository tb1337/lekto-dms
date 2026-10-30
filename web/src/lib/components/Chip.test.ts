import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import Chip from './Chip.svelte';

const name = createRawSnippet(() => ({ render: () => '<span>12 Monate</span>' }));

describe('a chip that toggles', () => {
	it('shows on by its look alone, at the width of its bolder name', () => {
		render(Chip, { pressed: true, children: name });
		const chip = screen.getByRole('button', { name: '12 Monate', pressed: true });
		// No check: the chips beside it stay where they are.
		expect(chip.querySelector('svg')).toBeNull();
		// The room of the bolder name, from its text.
		expect(chip.querySelector('.steady-weight')?.getAttribute('data-text')).toBe('12 Monate');
	});

	it('keeps the same parts when off', () => {
		render(Chip, { pressed: false, children: name });
		const chip = screen.getByRole('button', { name: '12 Monate', pressed: false });
		expect(chip.querySelector('svg')).toBeNull();
		expect(chip.querySelector('.steady-weight')?.getAttribute('data-text')).toBe('12 Monate');
	});
});
