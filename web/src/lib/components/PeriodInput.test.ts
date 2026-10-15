import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import PeriodInput from './PeriodInput.svelte';

describe('PeriodInput', () => {
	it('sets a whole month at once and shows it as that month', async () => {
		const onchange = vi.fn();
		render(PeriodInput, { value: { start: '', end: '' }, label: 'Bezugszeitraum', onchange });
		const month = screen.getByLabelText(m.field_period_month_of({ name: 'Bezugszeitraum' }));
		await fireEvent.input(month, { target: { value: '2028-02' } });
		expect(onchange).toHaveBeenLastCalledWith({ start: '2028-02-01', end: '2028-02-29' });
	});

	it('changes one end and keeps the other', async () => {
		const onchange = vi.fn();
		render(PeriodInput, {
			value: { start: '2026-09-01', end: '2026-09-30' },
			label: 'Bezugszeitraum',
			onchange
		});
		expect(
			(
				screen.getByLabelText(
					m.field_period_month_of({ name: 'Bezugszeitraum' })
				) as HTMLInputElement
			).value
		).toBe('2026-09');
		const end = screen.getByLabelText(m.field_period_to_of({ name: 'Bezugszeitraum' }));
		await fireEvent.input(end, { target: { value: '2026-09-14' } });
		expect(onchange).toHaveBeenLastCalledWith({ start: '2026-09-01', end: '2026-09-14' });
	});
});
