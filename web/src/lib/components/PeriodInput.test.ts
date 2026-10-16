import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import PeriodInput from './PeriodInput.svelte';

const NAME = 'Bezugszeitraum';

function notationField(): HTMLInputElement {
	return screen.getByLabelText(m.field_period_notation_of({ name: NAME })) as HTMLInputElement;
}

describe('PeriodInput', () => {
	it('sets from and to from a period as it is written, and then writes it in ISO', async () => {
		const onchange = vi.fn();
		render(PeriodInput, { value: { start: '', end: '' }, label: NAME, onchange });
		const field = notationField();
		await fireEvent.input(field, { target: { value: 'KW 17/2026' } });
		expect(onchange).toHaveBeenLastCalledWith({ start: '2026-04-20', end: '2026-04-26' });
		// What is typed stays until the field is left.
		expect(field.value).toBe('KW 17/2026');
		await fireEvent.blur(field);
		expect(field.value).toBe('2026-W17');
		await fireEvent.input(field, { target: { value: 'Februar 2028' } });
		expect(onchange).toHaveBeenLastCalledWith({ start: '2028-02-01', end: '2028-02-29' });
	});

	it('shows a changed end in the period, and a span with both ends', async () => {
		const onchange = vi.fn();
		render(PeriodInput, {
			value: { start: '2026-09-01', end: '2026-09-30' },
			label: NAME,
			onchange
		});
		expect(notationField().value).toBe('2026-09');
		const end = screen.getByLabelText(m.field_period_to_of({ name: NAME }));
		await fireEvent.input(end, { target: { value: '2026-09-14' } });
		expect(onchange).toHaveBeenLastCalledWith({ start: '2026-09-01', end: '2026-09-14' });
		expect(notationField().value).toBe('2026-09-01/2026-09-14');
	});

	it('says so when it cannot read the period, and keeps the last one', async () => {
		const onchange = vi.fn();
		render(PeriodInput, {
			value: { start: '2026-09-01', end: '2026-09-30' },
			label: NAME,
			onchange
		});
		const field = notationField();
		await fireEvent.input(field, { target: { value: 'nächsten Monat' } });
		await fireEvent.blur(field);
		expect(onchange).not.toHaveBeenCalled();
		expect(field.value).toBe('nächsten Monat');
		expect(field.getAttribute('aria-invalid')).toBe('true');
		expect(screen.getByText(m.field_period_unreadable())).toBeTruthy();
		// Changing an end ends it.
		const start = screen.getByLabelText(m.field_period_from_of({ name: NAME }));
		await fireEvent.input(start, { target: { value: '2026-09-14' } });
		expect(field.value).toBe('2026-09-14/2026-09-30');
		expect(screen.queryByText(m.field_period_unreadable())).toBeNull();
	});

	it('clears both ends when the period is emptied', async () => {
		const onchange = vi.fn();
		render(PeriodInput, {
			value: { start: '2026-09-01', end: '2026-09-30' },
			label: NAME,
			onchange
		});
		await fireEvent.input(notationField(), { target: { value: '' } });
		expect(onchange).toHaveBeenLastCalledWith({ start: '', end: '' });
	});
});
