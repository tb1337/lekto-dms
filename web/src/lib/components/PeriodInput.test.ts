import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import FieldValueInput from './FieldValueInput.svelte';
import PeriodInput from './PeriodInput.svelte';

const NAME = 'Bezugszeitraum';

function notationField(): HTMLInputElement {
	return screen.getByLabelText(m.field_period_notation_of({ name: NAME })) as HTMLInputElement;
}

describe('PeriodInput', () => {
	it('sets from and to from a period as it is written when the field is left', async () => {
		const onchange = vi.fn();
		render(PeriodInput, { value: { start: '', end: '' }, label: NAME, onchange });
		const field = notationField();
		await fireEvent.input(field, { target: { value: 'KW 17/2026' } });
		expect(onchange).not.toHaveBeenCalled();
		// What is typed stays until the field is left; then it is written in ISO.
		expect(field.value).toBe('KW 17/2026');
		await fireEvent.blur(field);
		expect(onchange).toHaveBeenCalledExactlyOnceWith({ start: '2026-04-20', end: '2026-04-26' });
		expect(field.value).toBe('2026-W17');
		await fireEvent.input(field, { target: { value: 'Februar 2028' } });
		await fireEvent.blur(field);
		expect(onchange).toHaveBeenLastCalledWith({ start: '2028-02-01', end: '2028-02-29' });
		expect(field.value).toBe('2028-02');
	});

	it('takes the period on Enter, without submitting, and keeps the text', async () => {
		const onchange = vi.fn();
		render(PeriodInput, { value: { start: '', end: '' }, label: NAME, onchange });
		const field = notationField();
		await fireEvent.input(field, { target: { value: 'Q2 2026' } });
		const enter = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true, bubbles: true });
		await fireEvent(field, enter);
		expect(enter.defaultPrevented).toBe(true);
		expect(onchange).toHaveBeenCalledExactlyOnceWith({ start: '2026-04-01', end: '2026-06-30' });
		expect(field.value).toBe('Q2 2026');
		expect(
			(screen.getByLabelText(m.field_period_from_of({ name: NAME })) as HTMLInputElement).value
		).toBe('2026-04-01');
	});

	it('does not walk through the readable prefixes of what is typed', async () => {
		const onchange = vi.fn();
		const onunreadable = vi.fn();
		render(PeriodInput, { value: { start: '', end: '' }, label: NAME, onchange, onunreadable });
		const field = notationField();
		for (const text of ['2', '2026', '2026-', '2026-W', '2026-W1', '2026-W17']) {
			await fireEvent.input(field, { target: { value: text } });
		}
		expect(onchange).not.toHaveBeenCalled();
		// Unreadable on the way (`2026-`), readable at the end.
		expect(onunreadable).toHaveBeenLastCalledWith(false);
		expect(onunreadable).toHaveBeenCalledWith(true);
		await fireEvent.blur(field);
		expect(onchange).toHaveBeenCalledExactlyOnceWith({ start: '2026-04-20', end: '2026-04-26' });
	});

	it('keeps the value while a typed continuation cannot be read, and says so', async () => {
		const onchange = vi.fn();
		const onunreadable = vi.fn();
		render(PeriodInput, {
			value: { start: '2026-09-01', end: '2026-09-30' },
			label: NAME,
			onchange,
			onunreadable
		});
		const field = notationField();
		await fireEvent.input(field, { target: { value: '2026' } });
		await fireEvent.input(field, { target: { value: '2026-1' } });
		await fireEvent.blur(field);
		expect(onchange).not.toHaveBeenCalled();
		expect(field.value).toBe('2026-1');
		expect(onunreadable).toHaveBeenLastCalledWith(true);
		expect(screen.getByText(m.field_period_unreadable())).toBeTruthy();
		await fireEvent.input(field, { target: { value: '2026-11' } });
		expect(onunreadable).toHaveBeenLastCalledWith(false);
		await fireEvent.blur(field);
		expect(onchange).toHaveBeenCalledExactlyOnceWith({ start: '2026-11-01', end: '2026-11-30' });
	});

	it('takes a span as a whole, not its first day', async () => {
		const onchange = vi.fn();
		render(PeriodInput, { value: { start: '', end: '' }, label: NAME, onchange });
		const field = notationField();
		await fireEvent.input(field, { target: { value: '1.3.2026' } });
		await fireEvent.input(field, { target: { value: '1.3.2026 bis 14.3.2026' } });
		await fireEvent.blur(field);
		expect(onchange).toHaveBeenCalledExactlyOnceWith({ start: '2026-03-01', end: '2026-03-14' });
	});

	it('reports readable again when it is removed', async () => {
		const onunreadable = vi.fn();
		const { unmount } = render(PeriodInput, {
			value: { start: '', end: '' },
			label: NAME,
			onunreadable
		});
		await fireEvent.input(notationField(), { target: { value: 'nächsten Monat' } });
		expect(onunreadable).toHaveBeenLastCalledWith(true);
		unmount();
		expect(onunreadable).toHaveBeenLastCalledWith(false);
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

	it('drops what was typed when the value comes again from outside, also the same period', async () => {
		// Issue #68: the form is reset or loaded again after an unreadable text was typed.
		const onunreadable = vi.fn();
		const september = { start: '2026-09-01', end: '2026-09-30' };
		const { rerender } = render(PeriodInput, { value: september, label: NAME, onunreadable });
		const field = notationField();
		await fireEvent.input(field, { target: { value: 'nächsten Monat' } });
		await fireEvent.blur(field);
		expect(field.value).toBe('nächsten Monat');
		expect(field.getAttribute('aria-invalid')).toBe('true');
		await rerender({ value: { ...september } });
		expect(field.value).toBe('2026-09');
		expect(field.getAttribute('aria-invalid')).toBeNull();
		expect(onunreadable).toHaveBeenLastCalledWith(false);
	});

	it('keeps its own changes and drops what was typed on a reset, also when bound', async () => {
		// Bound, as the document form binds it through the field's input.
		const field = { id: 'f1', name: NAME, data_type: 'period' } as FieldDefinition;
		const september = { start: '2026-09-01', end: '2026-09-30' };
		const { rerender } = render(FieldValueInput, { field, id: 'f1', value: september });
		const input = screen.getByPlaceholderText(m.field_period_placeholder()) as HTMLInputElement;
		await fireEvent.input(input, { target: { value: 'Q2 2026' } });
		await fireEvent.keyDown(input, { key: 'Enter' });
		expect(input.value).toBe('Q2 2026');
		await fireEvent.input(input, { target: { value: 'nächsten Monat' } });
		await fireEvent.blur(input);
		expect(input.value).toBe('nächsten Monat');
		// The form loads it again with the period it now holds: the same as before.
		await rerender({ value: { start: '2026-04-01', end: '2026-06-30' } });
		expect(input.value).toBe('2026-Q2');
	});

	it('clears both ends when the period is emptied', async () => {
		const onchange = vi.fn();
		render(PeriodInput, {
			value: { start: '2026-09-01', end: '2026-09-30' },
			label: NAME,
			onchange
		});
		await fireEvent.input(notationField(), { target: { value: '' } });
		await fireEvent.blur(notationField());
		expect(onchange).toHaveBeenLastCalledWith({ start: '', end: '' });
	});
});
