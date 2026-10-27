import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

// The real picker, not the stand-in of the other component tests (`tests/setup.ts`).
vi.unmock('#lib/components/DateInput.svelte');
const { default: DateInput } = await import('./DateInput.svelte');

describe('DateInput', () => {
	it('shows a day in segments of the UI language, with a calendar beside them', () => {
		render(DateInput, { value: '2026-10-26', label: 'Document date' });
		const field = screen.getByRole('group', { name: 'Document date' });
		const parts = [...field.querySelectorAll('[data-segment]')]
			.filter((segment) => segment.getAttribute('data-segment') !== 'literal')
			.map((segment) => segment.textContent?.trim())
			.filter(Boolean);
		expect(parts.sort()).toEqual(['10', '2026', '26']);
		expect(screen.getByRole('button')).toBeTruthy();
	});

	it('stays empty without a day', () => {
		render(DateInput, { value: '', label: 'Due' });
		const field = screen.getByRole('group', { name: 'Due' });
		expect(field.textContent).not.toMatch(/\d/);
	});
});
